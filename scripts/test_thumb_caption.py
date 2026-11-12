"""Оффлайн-тест подписи плитки с разрешением картинки (v0.8.4).

Пожелание: «во вкладке "Мои картинки", в блоке со списком файлов,
под маленькими изображениями — не только имя файла, но и разрешение
картинки».

Проверяет:
1. формат строки разрешения (_dims_text: «1920×1080», как в статусе
   полноэкранного просмотра);
2. tEXt-чанк кэша миниатюр: запись/чтение через настоящий PNG, честный
   (0, 0) для чанка-мусора и для старых записей без чанка;
3. imgload.load_file_ex: исходное разрешение для PNG и JPEG, при
   уменьшении до max_side возвращается именно ИСХОДНЫЙ размер, для
   мусора и отсутствующего файла — (null, ошибка, 0, 0);
4. обратная совместимость load_bytes (кортеж из двух, как раньше);
5. _ThumbTask напрямую: разрешение приходит и при декоде, и при
   попадании в кэш (когда оригинал не читается вовсе);
6. в живом вьюере: миниатюры загрузились, текст плитки остался чистым
   именем файла, разрешение — в отдельной роли («800×600»);
7. sizeHint делегата выше штатного ровно на одну строку шрифта
   (ширина не тронута) — лента не «прыгает», когда разрешение доезжает;
8. редактор переименования получает только имя файла, без разрешения;
9. отрисовка делегата без роли и с ролью не падает;
10. смена папки чистит очередь разрешений, у новой папки — свои размеры;
11. смоук: версия 0.8.23.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_thumb_caption.py
"""

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QSize, Qt, QThreadPool
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QStyledItemDelegate

from app import __version__  # noqa: E402
from app.core import i18n, imgload
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer, _ThumbSignals, _ThumbTask

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(app, cond, timeout_s: float = 20.0) -> bool:
    deadline = __import__("time").monotonic() + timeout_s
    while __import__("time").monotonic() < deadline:
        if cond():
            return True
        app.processEvents()
    return bool(cond())


def make_img(path: str, w: int, h: int, color: str, fmt: str = "PNG") -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(path, fmt)


_KEEP: list = []   # живые ссылки на задачи/сигналы: пул не держит Python-обёртки,
                   # GC может собрать их до доставки сигнала (сегфолт в offscreen)


def run_thumb_task(path: str, cache_dir: str, results: list) -> None:
    """Прогнать _ThumbTask в общем пуле и собрать аргументы ready()."""
    signals = _ThumbSignals()
    signals.ready.connect(lambda *a: results.append(a))
    st = os.stat(path)
    task = _ThumbTask(path, 0, 1, signals, cache_dir, st.st_size, st.st_mtime)
    _KEEP.append((task, signals))
    QThreadPool.globalInstance().start(task)


class _Loc:
    HomeLocation = 0
    PicturesLocation = 1
    GenericCacheLocation = 2


class FakeStdPaths:
    StandardLocation = _Loc

    @staticmethod
    def writableLocation(_kind) -> str:
        return tempfile.mkdtemp(prefix="ih_cap_home_")


class FakeSI:
    def __init__(self, path: str):
        self._path = path

    def isValid(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def isReady(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def rootPath(self) -> str:  # noqa: N802 (Qt API)
        return self._path

    def displayName(self) -> str:  # noqa: N802 (Qt API)
        return self._path

    def fileSystemType(self) -> bytes:  # noqa: N802 (Qt API)
        return b"ext4"

    def bytesTotal(self) -> int:  # noqa: N802 (Qt API)
        return 0

    def bytesFree(self) -> int:  # noqa: N802 (Qt API)
        return 0


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ih_cap_")
    cache_dir = tempfile.mkdtemp(prefix="ih_cap_cache_")

    lv.QStandardPaths = FakeStdPaths
    lv.QStorageInfo = types.SimpleNamespace(mountedVolumes=lambda: [FakeSI(tmp)])

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    i18n.set_lang("ru", persist=False)

    # ---------- 1. формат строки ----------
    check("формат: «1920×1080»", lv._dims_text(1920, 1080) == "1920×1080",
          lv._dims_text(1920, 1080))

    # ---------- 2. tEXt-чанк кэша ----------
    probe = QImage(30, 20, QImage.Format.Format_RGB32)
    probe.fill(QColor("teal"))
    probe.setText(lv._DIMS_TEXT_KEY, "800x600")
    pth = os.path.join(tmp, "probe.png")
    assert probe.save(pth, "PNG")
    back = QImage(pth)
    check("чанк: round-trip через PNG", lv._dims_from_cache(back) == (800, 600),
          str(lv._dims_from_cache(back)))
    plain = QImage(10, 10, QImage.Format.Format_RGB32)   # чанка нет — старый кэш
    check("чанк: нет чанка → (0, 0)", lv._dims_from_cache(plain) == (0, 0))
    broken = QImage(10, 10, QImage.Format.Format_RGB32)
    broken.setText(lv._DIMS_TEXT_KEY, "мусор")
    check("чанк: мусор → (0, 0)", lv._dims_from_cache(broken) == (0, 0))

    # ---------- 3. load_file_ex ----------
    png = os.path.join(tmp, "big.png")
    make_img(png, 800, 600, "tomato")
    img, err, w, h = imgload.load_file_ex(png)
    check("load_file_ex: PNG 800×600",
          not img.isNull() and not err and (w, h) == (800, 600), f"{(w, h)} {err}")
    img2, err2, w2, h2 = imgload.load_file_ex(png, max_side=100)
    check("load_file_ex: max_side сжимает, исходник прежний",
          not img2.isNull() and max(img2.width(), img2.height()) <= 100
          and (w2, h2) == (800, 600), f"img={img2.width()}x{img2.height()} orig={(w2, h2)}")
    jpg = os.path.join(tmp, "std.jpg")
    make_img(jpg, 640, 480, "steelblue", "JPEG")
    _img3, err3, w3, h3 = imgload.load_file_ex(jpg)
    check("load_file_ex: JPEG 640×480",
          not err3 and (w3, h3) == (640, 480), f"{(w3, h3)} {err3}")
    junk = os.path.join(tmp, "junk.png")
    with open(junk, "wb") as f:
        f.write("это не картинка вообще".encode("utf-8"))
    img4, err4, w4, h4 = imgload.load_file_ex(junk)
    check("load_file_ex: мусор → (null, ошибка, 0, 0)",
          img4.isNull() and bool(err4) and (w4, h4) == (0, 0), err4)
    img5, err5, w5, h5 = imgload.load_file_ex(os.path.join(tmp, "нет.png"))
    check("load_file_ex: нет файла → (null, ошибка, 0, 0)",
          img5.isNull() and bool(err5) and (w5, h5) == (0, 0), err5)

    # ---------- 4. совместимость load_bytes ----------
    data = open(png, "rb").read()
    pair = imgload.load_bytes(data)
    check("load_bytes: кортеж из двух, как раньше",
          len(pair) == 2 and not pair[0].isNull() and not pair[1])

    # ---------- 5. _ThumbTask: декод и кэш ----------
    results: list = []
    run_thumb_task(png, cache_dir, results)
    check("задача: разрешение пришло с декода",
          wait_until(app, lambda: len(results) == 1) and len(results[0]) == 5
          and results[0][3:5] == (800, 600),
          str(results))
    cache_files = [n for n in os.listdir(cache_dir) if n.endswith(".png")]
    check("задача: кэш-файл появился", len(cache_files) == 1, str(cache_files))
    results.clear()
    run_thumb_task(png, cache_dir, results)
    check("задача: разрешение пришло ИЗ КЭША",
          wait_until(app, lambda: len(results) == 1) and results[0][3:5] == (800, 600),
          str(results))

    # ---------- 6-9. живой вьюер ----------
    folder = tempfile.mkdtemp(prefix="ih_cap_imgs_")
    make_img(os.path.join(folder, "a.png"), 800, 600, "tomato")
    make_img(os.path.join(folder, "b.png"), 1920, 1080, "navy")

    viewer = LocalViewer()
    viewer.resize(900, 700)
    viewer.show()
    viewer.load_folder(folder)
    ok = wait_until(app, lambda: (
        viewer.list.count() == 2
        and viewer.list.item(0).data(lv._RES_ROLE)
        and viewer.list.item(1).data(lv._RES_ROLE)))
    check("вьюер: у обеих плиток есть разрешение", ok,
          f"{[viewer.list.item(i).data(lv._RES_ROLE) for i in range(viewer.list.count())]}")
    check("вьюер: текст плитки — чистое имя файла",
          viewer.list.item(0).text() == "a.png" and viewer.list.item(1).text() == "b.png",
          f"{viewer.list.item(0).text()!r}, {viewer.list.item(1).text()!r}")
    check("вьюер: роль плитки 0 — «800×600»",
          viewer.list.item(0).data(lv._RES_ROLE) == "800×600",
          str(viewer.list.item(0).data(lv._RES_ROLE)))
    check("вьюер: роль плитки 1 — «1920×1080»",
          viewer.list.item(1).data(lv._RES_ROLE) == "1920×1080",
          str(viewer.list.item(1).data(lv._RES_ROLE)))

    # ---------- 7. sizeHint: запас под вторую строку ----------
    dlg = viewer.list.itemDelegate()
    idx = viewer.list.indexFromItem(viewer.list.item(0))
    opt = QStyleOptionViewItem()
    opt.font = QApplication.font()
    opt.fontMetrics = QFontMetrics(opt.font)
    opt.decorationSize = QSize(lv.THUMB, lv.THUMB)
    opt.rect = idx.data(Qt.SizeHintRole) or __import__("PySide6.QtCore", fromlist=["QRect"]).QRect(0, 0, 300, 300)
    plain_hint = QStyledItemDelegate().sizeHint(opt, idx)
    thumb_hint = dlg.sizeHint(opt, idx)
    extra = QFontMetrics(opt.font).height()
    check("sizeHint: выше штатного на одну строку",
          thumb_hint.height() == plain_hint.height() + extra,
          f"{thumb_hint.height()} против {plain_hint.height()} + {extra}")
    check("sizeHint: ширина не тронута",
          thumb_hint.width() == plain_hint.width(),
          f"{thumb_hint.width()} против {plain_hint.width()}")

    # ---------- 8. редактор переименования без разрешения ----------
    editor = dlg.createEditor(viewer.list, opt, idx)
    dlg.setEditorData(editor, idx)
    check("редактор: только имя файла, без разрешения",
          editor.text() == "a.png", repr(editor.text()))
    editor.deleteLater()

    # ---------- 9. отрисовка без роли и с ролью ----------
    no_res = viewer.list.indexFromItem(viewer.list.item(1))
    viewer.list.item(no_res.row()).setData(lv._RES_ROLE, None)
    ok_paint = True
    try:
        canvas = QImage(260, 280, QImage.Format.Format_RGB32)
        canvas.fill(Qt.white)
        p = QPainter(canvas)
        dlg.paint(p, opt, no_res)
        dlg.paint(p, opt, idx)          # с разрешением
        p.end()
    except Exception as exc:            # noqa: BLE001
        ok_paint = False
        print("    paint error:", exc)
    check("paint: без роли и с ролью — без ошибок", ok_paint)

    # ---------- 10. смена папки чистит очередь ----------
    folder2 = tempfile.mkdtemp(prefix="ih_cap_imgs2_")
    make_img(os.path.join(folder2, "tiny.png"), 48, 48, "olive")
    viewer.load_folder(folder2)
    check("смена папки: очередь разрешений пуста",
          viewer._pending_dims == {} and viewer._pending_thumbs == {},
          str(viewer._pending_dims))
    ok2 = wait_until(app, lambda: (
        viewer.list.count() == 1
        and viewer.list.item(0).data(lv._RES_ROLE) is not None))
    check("смена папки: у новой плитки своё разрешение",
          ok2 and viewer.list.item(0).data(lv._RES_ROLE) == "48×48",
          str(viewer.list.item(0).data(lv._RES_ROLE) if viewer.list.count() else None))

    # ---------- 11. смоук ----------
    check("версия 0.8.23", __version__ == "0.8.23", __version__)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
