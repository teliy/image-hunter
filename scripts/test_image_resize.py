"""Оффлайн-тест изменения размера картинки мышью и кнопки сохранения (v0.8.6).

Пожелание: «добавь функцию resize картинки, чтобы можно было мышкой задать
размер картинки в окне предпросмотра, ну и конечно кнопку сохранения».

Проверяет:
1. математику: угол — пропорционально, края — одна сторона, пределы
   (_clamp_resize: минимум 1×1, сторона ≤ 16383, площадь ≤ 64 Мп);
2. свободное имя «имя_ШxВ.ext» с суффиксами -1, -2 при конфликте;
3. формат записи по расширению (png/jpg/webp/tiff, AVIF → .png);
4. задачу записи напрямую: файл нового размера, оригинал цел, журнал,
   конфликт имён, JPEG из картинки с альфой (белый фон), честная ошибка;
5. живой вьюер: кнопки на тулбаре, вход в режим, показ ровно в целевом
   размере, статус «✂ новый из исходник», рамка с рукоятками;
6. рукоятки _ResizeView: handle_at на угле/краях и мимо, перетаскивание
   честной доставкой событий (press → move → release), бейдж размера;
7. сохранение из режима: файл на диске, статус «Сохранено», режим
   закрылся, лента обновилась и открыла новый файл, повтор — без затираний;
8. Esc и «◱ Вписать» закрывают режим; зум в режиме игнорируется;
   смена картинки закрывает; GIF и пустой просмотр — кнопка погашена;
9. локализация ru/en/zh новых кнопок;
10. смоук: версия 0.8.10.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_image_resize.py
"""

import io
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, QSize, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from app import __version__  # noqa: E402
from app.core import applog, i18n
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer, _ResizeSaveTask, _ResizeSignals, _ResizeView

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


def make_gif(path: str, w: int = 120, h: int = 90) -> None:
    """Валидный анимированный GIF — как в test_stability.py (Qt GIF-плагин
    читает, но не пишет, поэтому собирает Pillow)."""
    from PIL import Image

    frames = [Image.new("P", (w, h), c) for c in (220, 130, 60)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    with open(path, "wb") as fh:
        fh.write(buf.getvalue())


def row_of(viewer: LocalViewer, name: str) -> int:
    for i in range(viewer.list.count()):
        if viewer.list.item(i).text() == name:
            return i
    return -1


def has_pixmap(viewer: LocalViewer) -> bool:
    """Показана ли картинка (в Qt6 QLabel.pixmap() возвращает null-QPixmap, а не None)."""
    pm = viewer.view_label.pixmap()
    return pm is not None and not pm.isNull()


def drag(view: _ResizeView, handle: int, dx: int, dy: int) -> None:
    """Честная доставка событий мыши: press на рукоятке → move → release."""
    r = view.pixmap_rect()
    if handle == _ResizeView.HANDLE_CORNER:
        p = QPointF(r.right(), r.bottom())
    elif handle == _ResizeView.HANDLE_RIGHT:
        p = QPointF(r.right(), (r.top() + r.bottom()) / 2)
    else:
        p = QPointF((r.left() + r.right()) / 2, r.bottom())
    view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, p,
                                     Qt.MouseButton.LeftButton,
                                     Qt.MouseButton.LeftButton, Qt.NoModifier))
    view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, p + QPointF(dx, dy),
                                    Qt.NoButton, Qt.MouseButton.LeftButton,
                                    Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,
                                       p + QPointF(dx, dy),
                                       Qt.MouseButton.LeftButton,
                                       Qt.NoButton, Qt.NoModifier))


class _Loc:
    HomeLocation = 0
    PicturesLocation = 1
    GenericCacheLocation = 2


class FakeStdPaths:
    StandardLocation = _Loc

    @staticmethod
    def writableLocation(_kind) -> str:
        return tempfile.mkdtemp(prefix="ih_rs_home_")


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


_KEEP: list = []   # живые ссылки на задачи/сигналы: пул не держит Python-обёртки


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ih_rs_")
    lv.QStandardPaths = FakeStdPaths
    lv.QStorageInfo = types.SimpleNamespace(mountedVolumes=lambda: [FakeSI(tmp)])

    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    i18n.set_lang("ru", persist=False)
    applog.setup()
    log_lines: list[str] = []
    applog.bridge.record.connect(lambda lvl, line: log_lines.append(line))

    # ---------- 1. математики размера ----------
    orig = QSize(800, 600)
    t = lv._resize_target_for(_ResizeView.HANDLE_CORNER, QSize(800, 600),
                              -400, -50, orig)
    check("математика: угол пропорционален (800×600 → 400×300)",
          (t.width(), t.height()) == (400, 300), f"{t.width()}x{t.height()}")
    t = lv._resize_target_for(_ResizeView.HANDLE_RIGHT, QSize(800, 600),
                              -300, 999, orig)
    check("математика: правый край — только ширина",
          (t.width(), t.height()) == (500, 600), f"{t.width()}x{t.height()}")
    t = lv._resize_target_for(_ResizeView.HANDLE_BOTTOM, QSize(800, 600),
                              999, -100, orig)
    check("математика: нижний край — только высота",
          (t.width(), t.height()) == (800, 500), f"{t.width()}x{t.height()}")
    t = lv._resize_target_for(_ResizeView.HANDLE_CORNER, QSize(800, 600),
                              -5000, 0, orig)
    check("математика: меньше 1×1 нельзя",
          t.width() >= 1 and t.height() >= 1, f"{t.width()}x{t.height()}")
    t = lv._resize_target_for(_ResizeView.HANDLE_RIGHT, QSize(16000, 100),
                              500, 0, orig)
    check("математика: сторона ограничена 16383",
          t.width() == 16383, str(t.width()))
    w, h = lv._clamp_resize(20000, 10000)     # 200 Мп → зажим по площади
    check("математика: площадь ограничена 64 Мп",
          w * h <= lv._RESIZE_MAX_PIXELS, f"{w}x{h}")
    w, h = lv._clamp_resize(-5, 0)
    check("математика: минимум 1×1", (w, h) == (1, 1), f"{w}x{h}")

    # ---------- 2. свободное имя и форматы ----------
    names_dir = tempfile.mkdtemp(prefix="ih_rs_names_")
    check("имя: свободное «cat_320x240.png»",
          lv._free_resize_name(names_dir, "cat", 320, 240, ".png")
          == "cat_320x240.png")
    open(os.path.join(names_dir, "cat_320x240.png"), "wb").close()
    check("имя: конфликт → «cat_320x240-1.png»",
          lv._free_resize_name(names_dir, "cat", 320, 240, ".png")
          == "cat_320x240-1.png")
    open(os.path.join(names_dir, "cat_320x240-1.png"), "wb").close()
    check("имя: два конфликта → «cat_320x240-2.png»",
          lv._free_resize_name(names_dir, "cat", 320, 240, ".png")
          == "cat_320x240-2.png")
    check("формат: png → PNG", lv._resize_format_for(".png") == ("PNG", None))
    check("формат: jpeg → JPEG 92", lv._resize_format_for(".jpeg") == ("JPEG", 92))
    check("формат: webp → WEBP 90", lv._resize_format_for(".WEBP") == ("WEBP", 90))
    check("формат: tif → TIFF", lv._resize_format_for(".tif") == ("TIFF", None))
    check("формат: AVIF Qt не пишет → .png",
          lv._resize_save_ext(".avif") == ".png"
          and lv._resize_save_ext(".avifs") == ".png")
    check("формат: неизвестное расширение → .png",
          lv._resize_save_ext(".xyz") == ".png")

    # ---------- 3. задача записи напрямую ----------
    task_dir = tempfile.mkdtemp(prefix="ih_rs_task_")
    src_png = os.path.join(task_dir, "cat.png")
    make_img(src_png, 640, 480, "tomato")
    img = QImage(src_png)
    sig = _ResizeSignals()
    results: list = []
    sig.done.connect(lambda *a: results.append(a))
    task = _ResizeSaveTask(img, 320, 240, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task, sig))
    QThreadPool.globalInstance().start(task)
    check("задача: файл записан и доложился",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is True
          and os.path.basename(results[0][1]) == "cat_320x240.png",
          str(results))
    out = QImage(results[0][1]) if results else QImage()
    check("задача: размер результата ровно 320×240",
          not out.isNull() and out.size() == QSize(320, 240),
          f"{out.width()}x{out.height()}")
    check("задача: оригинал не тронут",
          QImage(src_png).size() == QSize(640, 480))
    check("задача: событие в журнале",
          any("cat_320x240.png" in ln and "cat.png" in ln for ln in log_lines),
          "\n".join(log_lines)[-200:] if log_lines else "журнал пуст")

    # конфликт имён в задаче
    results.clear()
    task2 = _ResizeSaveTask(img, 320, 240, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task2, sig))
    QThreadPool.globalInstance().start(task2)
    check("задача: конфликт имён → «cat_320x240-1.png»",
          wait_until(app, lambda: len(results) == 1)
          and os.path.basename(results[0][1]) == "cat_320x240-1.png", str(results))

    # JPEG из картинки с альфой — белый фон вместо чёрной прозрачности
    rgba = QImage(64, 48, QImage.Format.Format_ARGB32)
    rgba.fill(Qt.GlobalColor.transparent)
    task_dir2 = tempfile.mkdtemp(prefix="ih_rs_task2_")
    results.clear()
    task3 = _ResizeSaveTask(rgba, 32, 24, task_dir2, "alpha", ".jpg",
                            "alpha.jpg", sig)
    _KEEP.append((task3, sig))
    QThreadPool.globalInstance().start(task3)
    check("задача: JPEG из картинки с альфой записался",
          wait_until(app, lambda: len(results) == 1) and results[0][0] is True,
          str(results))
    jpg = QImage(os.path.join(task_dir2, "alpha_32x24.jpg"))
    check("задача: прозрачность JPEG стала белой, а не чёрной",
          not jpg.isNull() and jpg.pixelColor(0, 0).value() > 200,
          jpg.pixelColor(0, 0).name() if not jpg.isNull() else "null")

    # честная ошибка (папки нет)
    results.clear()
    task4 = _ResizeSaveTask(img, 10, 10,
                            os.path.join(task_dir, "нет", "глубже"),
                            "cat", ".png", "cat.png", sig)
    _KEEP.append((task4, sig))
    QThreadPool.globalInstance().start(task4)
    check("задача: несуществующая папка — честная ошибка",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is False and results[0][4], str(results))

    # ---------- 4-8. живой вьюер ----------
    folder = tempfile.mkdtemp(prefix="ih_rs_imgs_")
    make_img(os.path.join(folder, "cat.png"), 800, 600, "tomato")
    make_img(os.path.join(folder, "dog.png"), 300, 200, "navy")
    make_gif(os.path.join(folder, "z_anim.gif"))   # «z_» — чтобы была последней

    viewer = LocalViewer()
    viewer.resize(1000, 720)
    viewer.show()
    viewer.load_folder(folder)
    ok = wait_until(app, lambda: viewer.list.count() == 3
                    and has_pixmap(viewer) and viewer.btn_resize.isEnabled())
    check("вьюер: папка открыта, картинка показана", ok)
    check("вьюер: открыта первая плитка (cat.png)",
          viewer.list.currentItem() is not None
          and viewer.list.currentItem().text() == "cat.png",
          viewer.list.currentItem().text() if viewer.list.currentItem() else "—")

    check("кнопка: «⇲ Размер» на месте и checkable",
          hasattr(viewer, "btn_resize") and viewer.btn_resize.isCheckable())
    check("кнопка: включена для статичной картинки", viewer.btn_resize.isEnabled())
    check("кнопка: «💾 Сохранить» скрыта вне режима",
          not viewer.btn_resize_save.isVisible())

    # вход в режим
    viewer.set_resize_mode(True)
    check("режим: включился", viewer._resize_mode)
    check("режим: кнопка «⇲ Размер» нажата", viewer.btn_resize.isChecked())
    check("режим: «💾 Сохранить» видна и включена",
          viewer.btn_resize_save.isVisible() and viewer.btn_resize_save.isEnabled())
    pm = viewer.view_label.pixmap()
    check("режим: показ ровно в исходном размере 800×600",
          pm is not None and not pm.isNull() and pm.size() == QSize(800, 600),
          f"{pm.width()}x{pm.height()}" if pm else "None")
    check("режим: статус с подсказкой",
          "✂" in viewer.status.text() and "800×600" in viewer.status.text(),
          viewer.status.text())
    check("режим: рамка включена во вью", viewer.view_label._resize_on)

    # рукоятки: handle_at
    view = viewer.view_label
    r = view.pixmap_rect()
    check("рукоятки: угол найден",
          view.handle_at(QPoint(r.right() - 2, r.bottom() - 2))
          == _ResizeView.HANDLE_CORNER)
    check("рукоятки: правый край найден",
          view.handle_at(QPoint(r.right() - 1, (r.top() + r.bottom()) // 2))
          == _ResizeView.HANDLE_RIGHT)
    check("рукоятки: нижний край найден",
          view.handle_at(QPoint((r.left() + r.right()) // 2, r.bottom() - 1))
          == _ResizeView.HANDLE_BOTTOM)
    check("рукоятки: центр картинки — не рукоятка",
          view.handle_at(QPoint((r.left() + r.right()) // 2,
                                (r.top() + r.bottom()) // 2))
          == _ResizeView.HANDLE_NONE)
    check("рукоятки: мимо картинки — не рукоятка",
          view.handle_at(QPoint(0, 0)) == _ResizeView.HANDLE_NONE)

    # перетаскивание угла: пропорционально 800×600 → 400×300
    drag(view, _ResizeView.HANDLE_CORNER, -400, -300)
    check("драг угла: 800×600 → 400×300",
          viewer._resize_size == QSize(400, 300), str(viewer._resize_size))
    pm = view.pixmap()
    check("драг угла: пиксмап нового размера",
          pm is not None and not pm.isNull() and pm.size() == QSize(400, 300),
          f"{pm.width()}x{pm.height()}" if pm else "None")
    check("драг угла: статус «✂ 400×300 из 800×600»",
          "400×300" in viewer.status.text() and "800×600" in viewer.status.text(),
          viewer.status.text())
    check("драг угла: бейдж с размером", view._badge == "400×300", view._badge)

    # правый край: только ширина; нижний край: только высота
    drag(view, _ResizeView.HANDLE_RIGHT, -100, 55)
    check("драг правого края: ширина 300, высота 300",
          viewer._resize_size == QSize(300, 300), str(viewer._resize_size))
    drag(view, _ResizeView.HANDLE_BOTTOM, 55, -150)
    check("драг нижнего края: высота 150, ширина 300",
          viewer._resize_size == QSize(300, 150), str(viewer._resize_size))

    # отрисовка рамки/рукояток/бейджа не падает (render сам создаёт маляра)
    ok_paint = True
    try:
        canvas = QImage(900, 700, QImage.Format.Format_RGB32)
        canvas.fill(Qt.GlobalColor.darkGray)
        view.render(canvas)
    except Exception as exc:            # noqa: BLE001
        ok_paint = False
        print("    paint error:", exc)
    check("отрисовка: рамка с рукоятками и бейджем — без ошибок", ok_paint)

    # сохранение из режима
    viewer._on_resize_save()
    saved_path = os.path.join(folder, "cat_300x150.png")
    ok_saved = wait_until(app, lambda: os.path.lexists(saved_path))
    check("сохранение: файл «cat_300x150.png» появился", ok_saved)
    ok_strip = wait_until(app, lambda: (
        viewer.list.count() == 4
        and viewer.list.currentItem() is not None
        and viewer.list.currentItem().text() == "cat_300x150.png"))
    check("сохранение: лента обновилась и открыла новый файл", ok_strip,
          f"count={viewer.list.count()}, cur="
          f"{viewer.list.currentItem().text() if viewer.list.currentItem() else None}")
    check("сохранение: статус называет сохранённый файл или открытый результат",
          "cat_300x150.png" in viewer.status.text(), viewer.status.text())
    check("сохранение: оригинал не тронут",
          QImage(os.path.join(folder, "cat.png")).size() == QSize(800, 600))
    check("сохранение: режим закрылся",
          wait_until(app, lambda: not viewer._resize_mode))
    check("сохранение: размер файла ровно 300×150",
          os.path.lexists(saved_path)
          and QImage(saved_path).size() == QSize(300, 150),
          f"{QImage(saved_path).width()}x{QImage(saved_path).height()}"
          if os.path.lexists(saved_path) else "")
    check("сохранение: открыт результат, показ «вписан в окно»",
          has_pixmap(viewer) and viewer._mode == "fit")

    # повторное сохранение ТОГО ЖЕ размера ОТ ОРИГИНАЛА — без затираний
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(800, 600))
    viewer.set_resize_mode(True)
    viewer._resize_size = QSize(300, 150)   # тот же размер, что уже сохранён
    viewer._apply_resize(smooth=True)
    viewer._on_resize_save()
    dup_path = os.path.join(folder, "cat_300x150-1.png")
    check("сохранение: повтор → «cat_300x150-1.png», оригинал копии цел",
          wait_until(app, lambda: os.path.lexists(dup_path))
          and wait_until(app, lambda: not viewer._resize_mode))
    wait_until(app, lambda: viewer.list.count() == 5)

    # Esc закрывает режим, возвращая «вписать в окно»
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(800, 600))
    viewer.set_resize_mode(True)
    viewer._escape_search()
    check("Esc: режим закрылся", not viewer._resize_mode)
    check("Esc: вернулись к «вписать в окно»",
          viewer._mode == "fit" and has_pixmap(viewer))

    # «◱ Вписать» тоже закрывает
    viewer.set_resize_mode(True)
    viewer.fit_to_window()
    check("«◱»: режим закрылся", not viewer._resize_mode)

    # зум в режиме ресайса игнорируется
    viewer.set_resize_mode(True)
    viewer._resize_size = QSize(300, 150)
    viewer._apply_resize(smooth=True)
    viewer.zoom(1.25)
    viewer.set_manual_zoom(2.0)
    check("зум в режиме ресайса игнорируется",
          viewer._resize_mode and viewer._resize_size == QSize(300, 150),
          str(viewer._resize_size))
    viewer.set_resize_mode(False)

    # смена картинки закрывает режим
    viewer.set_resize_mode(True)
    check("смена: режим открыт перед кликом", viewer._resize_mode)
    viewer.list.setCurrentRow(row_of(viewer, "dog.png"))
    check("смена картинки: режим закрылся",
          wait_until(app, lambda: not viewer._resize_mode))
    check("смена картинки: новая картинка загрузилась",
          wait_until(app, lambda: viewer._pixmap is not None
                     and viewer._pixmap.size() == QSize(300, 200)))
    check("смена картинки: кнопка снова включена",
          viewer.btn_resize.isEnabled())

    # ---------- 9. GIF ----------
    viewer.list.setCurrentRow(row_of(viewer, "z_anim.gif"))
    check("GIF: анимация открылась",
          wait_until(app, lambda: viewer._movie is not None))
    check("GIF: кнопка «⇲ Размер» погашена", not viewer.btn_resize.isEnabled())
    viewer.btn_resize.setEnabled(True)   # «упрямый» клик всё равно не включит режим
    viewer.btn_resize.toggled.emit(True)
    check("GIF: режим не включается", not viewer._resize_mode)
    viewer.btn_resize.setEnabled(False)

    # ---------- 10. пустой просмотр ----------
    viewer.load_folder(tempfile.mkdtemp(prefix="ih_rs_empty_"))
    wait_until(app, lambda: viewer.list.count() == 0)
    check("пусто: кнопка погашена", not viewer.btn_resize.isEnabled())

    # ---------- 11. локализация ----------
    viewer.load_folder(folder)
    wait_until(app, lambda: viewer.list.count() == 5
               and viewer.btn_resize.isEnabled())
    i18n.set_lang("en", persist=False)
    check("en: текст кнопки", viewer.btn_resize.text() == "⇲ Resize",
          viewer.btn_resize.text())
    check("en: подсказка обновилась",
          "mouse" in viewer.btn_resize.toolTip().lower()
          or "drag" in viewer.btn_resize.toolTip().lower(),
          viewer.btn_resize.toolTip()[:60])
    check("en: «💾 Сохранить»", viewer.btn_resize_save.text() == "💾 Save",
          viewer.btn_resize_save.text())
    i18n.set_lang("zh", persist=False)
    check("zh: текст кнопки", viewer.btn_resize.text() == "⇲ 大小",
          viewer.btn_resize.text())
    i18n.set_lang("ru", persist=False)
    check("ru: текст кнопки вернулся", viewer.btn_resize.text() == "⇲ Размер",
          viewer.btn_resize.text())

    # ---------- 12. смоук ----------
    check("версия 0.8.10", __version__ == "0.8.10", __version__)

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
