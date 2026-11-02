"""Стабильность и скорость v0.7.11 — правки по итогам аудита кода.

Проверяет:
1) гонку имён при параллельном скачивании: запись через O_CREAT|O_EXCL —
   два файла с одинаковым именем больше не затирают друг друга
   (классический «os.path.exists → open» race окно имело всегда);
2) GIF открывается без чтения файла в GUI-потоке: анимация строится
   из памяти поверх QBuffer (на подвисшем сетевом диске QMovie(path)
   замораживал окно на сетевой тайм-аут);
3) битый GIF показывает ошибку, а не падение;
4) смена плитки на лету не роняет отложенную анимацию;
5) рескейл «по размеру окна» отложен до паузы в ресайзе (80 мс) —
   перетаскивание края окна с большим фото больше не дёргается;
6) кнопка «Обновить» не плодит проверки при повторных кликах;
7) кэш корзины по корню диска (_drive_has_trash);
8) публичная подсветка show_in_tree (асинхронная прогулка) работает;
9) _http_get: реальный requests → сессия на поток, подмена в тестах → get.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_stability.py
"""

import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRunnable, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPixmap, QMovie  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import downloader, i18n, updates  # noqa: E402
from app.core.downloader import Downloader, _DownloadTask  # noqa: E402
from app.ui import local_viewer as lv  # noqa: E402
from app.ui.local_viewer import LocalViewer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def pump(app, ms: int = 300) -> None:
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


def wait_until(cond_fn, timeout_ms: int = 5000) -> bool:
    app = QApplication.instance()
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()
        if cond_fn():
            return True
    return False


# ---------- подмена requests (как в test_download_fallback) ----------

class FakeResp:
    def __init__(self, url=""):
        self.status_code = 200
        self.url = url
        self.headers = {"Content-Type": "image/png"}
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield b"\x89PNG-fake-" + os.urandom(32)

    def close(self):
        self.closed = True


class FakeRequests:
    def __init__(self):
        self.calls = 0

    def get(self, url, headers=None, timeout=None, stream=True):
        self.calls += 1
        return FakeResp(url)

    class exceptions:  # noqa: N270
        class HTTPError(Exception):
            pass


def make_png(path: str, size: int = 64) -> None:
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    assert img.save(path)


def make_gif(path: str) -> None:
    from PIL import Image

    frames = [Image.new("P", (24, 18), c) for c in (220, 130, 60)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    with open(path, "wb") as fh:
        fh.write(buf.getvalue())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru")
    st = QSettings("ImageHunter", "ImageHunter")
    for key in ("viewer/last_folder", "viewer/last_query", "viewer/splitter",
                "viewer/favorites"):
        st.remove(key)
    st.setValue("viewer/thumbs", True)

    serp = "https://duckduckgo.com/?q=x&iax=images&ia=images"

    # ---- 1. гонка имён: O_EXCL -------------------------------------------
    fake = FakeRequests()
    real_requests = downloader.requests
    downloader.requests = fake            # type: ignore[assignment]
    try:
        tmp = tempfile.mkdtemp(prefix="ih_race_")
        # окно гонки эмулируем: os.path.exists вечно False (как в момент,
        # когда оба потока ещё не создали файл); старый код давал обоим
        # задачам один путь, и второй затирал первый. O_EXCL этого не видит,
        # но проверяет атомарно средствами ОС — второй честно получает -1.
        real_exists = os.path.exists

        def lying_exists(_p):
            return False

        dl = Downloader()
        results: list[tuple[int, str, str]] = []
        dl.status_changed.connect(
            lambda rid, status, info: results.append((rid, status, info)))
        downloader.os.path.exists = lying_exists   # type: ignore[assignment]
        try:
            _DownloadTask(dl, 1, "https://cdn.example/a/pic.png", serp, tmp).run()
            _DownloadTask(dl, 2, "https://cdn.example/b/pic.png", serp, tmp).run()
        finally:
            downloader.os.path.exists = real_exists  # type: ignore[assignment]
        files = sorted(os.listdir(tmp))
        check("гонка имён: оба файла на диске, ничего не затёрто",
              files == ["pic-1.png", "pic.png"], str(files))
        check("гонка имён: оба скачивания отчитались успехом",
              [r[1] for r in results] == ["ok", "ok"], str(results))
        sizes = [os.path.getsize(os.path.join(tmp, f)) for f in files]
        check("гонка имён: оба файла не пусты", all(s > 0 for s in sizes),
              str(sizes))
        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        downloader.requests = real_requests   # type: ignore[assignment]

    # ---- 2. GIF: анимация из фонового чтения ------------------------------
    tmp_gif = tempfile.mkdtemp(prefix="ih_gif_")
    try:
        make_gif(os.path.join(tmp_gif, "anim.gif"))
        viewer = LocalViewer()
        viewer.resize(1000, 700)
        viewer.show()
        viewer.load_folder(tmp_gif)
        check("GIF-папка прочитана", wait_until(lambda: viewer.list.count() == 1))
        # первый файл выделяется автоматически (_fill_folder) — анимация грузится;
        # убедимся, что выбор дошёл до конца
        viewer.list.setCurrentRow(0)   # _show_index → _GifTask
        check("анимация построена из памяти",
              wait_until(lambda: viewer._movie is not None
                         and viewer._movie.state() == QMovie.MovieState.Running))
        movie = viewer._movie
        check("GIF валиден", movie.isValid())
        check("анимация показана в метке", viewer.view_label.movie() is movie)
        check("кадры анимации распознаны", movie.frameCount() >= 1,
              str(movie.frameCount()))
        check("курсор занятости снят", not viewer._view_busy and
              viewer._view_inflight == 0)
        check("статус называет файл", "anim.gif" in viewer.status.text(),
              viewer.status.text())

        # ---- 3. битый GIF: ошибка вместо падения --------------------------
        # (файл БЕЗ валидной подписи GIF: «GIF89a…» Qt счёл бы валидным
        # заголовком и просто не нашёл бы кадров)
        bad = os.path.join(tmp_gif, "broken")
        os.makedirs(bad, exist_ok=True)
        with open(os.path.join(bad, "broken.gif"), "wb") as fh:
            fh.write(b"\x00\x01\x02this-is-not-a-gif-at-all")
        viewer.load_folder(bad)
        check("папка с битым GIF прочитана",
              wait_until(lambda: viewer.list.count() == 1))
        viewer.list.setCurrentRow(0)
        check("битый GIF: анимации нет", wait_until(
            lambda: viewer._view_inflight == 0 and viewer._movie is None))
        check("битый GIF: показано сообщение об ошибке",
              "GIF" in viewer.view_label.text(), viewer.view_label.text())

        # ---- 4. смена плитки на лету не роняет отложенную анимацию --------
        viewer.load_folder(tmp_gif)
        check("GIF-папка перечитана", wait_until(lambda: viewer.list.count() == 1))
        viewer.list.setCurrentRow(0)
        viewer.load_folder(bad, entries=[])   # тут же ушли в другую папку
        pump(app, 600)
        check("устаревшая анимация не показана", viewer._movie is None)
        check("курсор занятости снят после смены папки",
              viewer._view_inflight == 0 and not viewer._view_busy)
    finally:
        shutil.rmtree(tmp_gif, ignore_errors=True)

    # ---- 5. рескейл после паузы в ресайзе ---------------------------------
    tmp_png = tempfile.mkdtemp(prefix="ih_resize_")
    try:
        make_png(os.path.join(tmp_png, "big.png"), size=600)
        viewer2 = LocalViewer()
        viewer2.resize(1000, 700)
        viewer2.show()
        viewer2.load_folder(tmp_png)
        check("папка с фото прочитана",
              wait_until(lambda: viewer2.list.count() == 1))
        viewer2.list.setCurrentRow(0)
        check("фото показано", wait_until(lambda: viewer2._pixmap is not None))
        viewer2._mode = "fit"
        viewer2._apply_mode()
        pump(app, 100)
        w_before = viewer2.view_label.pixmap().width()
        viewer2.resize(480, 420)   # окно стало меньше — fit должен ужать фото
        w_right_after = viewer2.view_label.pixmap().width()
        check("при ресайзе картинка НЕ пересчитывается сразу (отложена)",
              w_right_after == w_before, f"{w_before} → {w_right_after}")
        check("после паузы картинка ужата под окно",
              wait_until(lambda: viewer2.view_label.pixmap() is not None
                         and viewer2.view_label.pixmap().width() < w_before),
              f"было {w_before}")
    finally:
        shutil.rmtree(tmp_png, ignore_errors=True)

    # ---- 6. «Обновить» не плодит проверки ---------------------------------
    mw_holder: dict = {}

    class FakeTask(QRunnable):
        def __init__(self, signals):
            super().__init__()
            self.signals = signals
            mw_holder["created"] = mw_holder.get("created", 0) + 1

        def run(self):   # никогда не отвечает — диалога не будет
            pass

    orig_task = updates.VersionCheckTask
    updates.VersionCheckTask = FakeTask   # type: ignore[assignment]
    # _on_version_checked с пустым ответом показывает МОДАЛЬНЫЙ диалог —
    # в тесте подменяем (восстанавливаем в finally)
    from app.ui import main_window as mw_mod
    orig_warn = mw_mod.QMessageBox.warning
    mw_mod.QMessageBox.warning = (  # type: ignore[assignment]
        lambda *a, **k: mw_mod.QMessageBox.StandardButton.Ok)
    try:
        from app.ui.main_window import MainWindow

        mw = MainWindow()
        mw.check_updates()
        check("первый клик запустил ровно одну проверку",
              mw_holder.get("created") == 1 and mw._upd_checking is True)
        mw.check_updates()
        mw.check_updates()
        check("повторные клики ничего не запускают",
              mw_holder.get("created") == 1)
        mw._on_version_checked("")   # сброс флага, как после настоящей проверки
        check("после завершения проверки флаг снят", mw._upd_checking is False)
        mw.check_updates()
        check("следующая проверка снова возможна", mw_holder.get("created") == 2)
        mw._upd_checking = False   # не оставляем флаг: задача-пустышка не ответит
    finally:
        updates.VersionCheckTask = orig_task   # type: ignore[assignment]
        mw_mod.QMessageBox.warning = orig_warn  # type: ignore[assignment]

    # ---- 7. кэш корзины ----------------------------------------------------
    tmp_trash = tempfile.mkdtemp(prefix="ih_trash_")
    try:
        a = lv._drive_has_trash(os.path.join(tmp_trash, "x.png"))
        b = lv._drive_has_trash(os.path.join(tmp_trash, "y.png"))
        check("на Linux у дисков корзины нет (None), вызов стабилен",
              a is None and b is None, f"{a}/{b}")
        check("не-Windows путь не пишется в кэш", not lv._TRASH_DRIVE_CACHE)
    finally:
        shutil.rmtree(tmp_trash, ignore_errors=True)

    # ---- 8. show_in_tree: асинхронная подсветка ----------------------------
    # (временная папка — внутри «Домой»: в дереве нет вершин вне домашних
    # дисков, в песочнице корень / — виртуальная ФС и в дереве не показывается)
    tmp_tree = tempfile.mkdtemp(prefix="ih_tree_", dir=os.path.expanduser("~"))
    try:
        nested = os.path.join(tmp_tree, "alpha", "beta")
        os.makedirs(nested)
        viewer3 = LocalViewer()
        viewer3.load_folder(tmp_tree, entries=[])
        viewer3.show_in_tree(nested)

        def _current_path():
            it = viewer3.tree.currentItem()
            return os.path.normpath(it.data(0, Qt.ItemDataRole.UserRole) or "") \
                if it is not None else ""

        ok = wait_until(lambda: _current_path() == os.path.normpath(nested),
                        timeout_ms=4000)
        check("show_in_tree подсвечивает папку (асинхронная прогулка)", ok)
    finally:
        shutil.rmtree(tmp_tree, ignore_errors=True)

    # ---- 9. _http_get: сессия на поток, подмена тестов ----------------------
    real = downloader._http_get()
    check("реальный requests: возвращён метод сессии",
          getattr(getattr(real, "__self__", None), "__class__", None).__name__
          == "Session", str(getattr(getattr(real, "__self__", None),
                                    "__class__", None)))
    downloader.requests = FakeRequests()   # type: ignore[assignment]
    try:
        fallback = downloader._http_get()
        check("подмена requests: запасной путь requests.get",
              fallback.__self__ is downloader.requests
              and fallback.__name__ == "get")
    finally:
        downloader.requests = real_requests   # type: ignore[assignment]

    # ---- 10. QPixmap зум не задет правками (смоук-поверхность) --------------
    pm = QPixmap(4, 4)
    check("QPixmap жив", not pm.isNull())

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
