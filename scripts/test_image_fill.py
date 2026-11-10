"""Оффлайн-тест пипетки и закрашивания выделенной области (v0.8.8).

Пожелание: «нужно добавить пипетку, которая считывает цвет пикселя и сделать
функцию закрашивания выбранной области цветом который выбран пипеткой».

Проверяет:
1. свободное имя «имя_fill.ext» с суффиксами -1, -2 при конфликте;
2. задачу записи напрямую: файл ровно исходного размера (закрашенный
   прямоугольник — взятого цвета, остальное — пиксели оригинала), оригинал
   цел, журнал, конфликт имён, JPEG из картинки с альфой (белый фон),
   честная ошибка;
3. живой вьюер: кнопки «💧 Пипетка» и «🪣 Закрасить», образец цвета на панели;
4. режим пипетки: наведение показывает цвет в статусе, клик берёт цвет
   (образец + буфер обмена + статус);
5. правый клик по картинке берёт цвет БЕЗ режима (обычный просмотр и
   режим обрезки — выделение при этом не ломается);
6. закрашивание: без цвета — честная подсказка; с цветом — показ
   перекрасился сразу, файл «имя_fill.ext» записан (прямоугольник —
   цветом, остальное — оригинал), лента обновилась и открыла результат,
   режим закрылся, оригинал цел, повтор — без затираний;
7. Esc закрывает режим пипетки; режимы «💧»/«✂»/«⇲» взаимоисключающие;
   смена картинки/папки закрывает пипетку; GIF и пустой просмотр —
   кнопка погашена;
8. локализация ru/en/zh новых кнопок;
9. смоук: версия 0.8.13.

Запуск: LD_LIBRARY_PATH=… .venv/bin/python scripts/test_image_fill.py
(QT_QPA_PLATFORM=offscreen ставится ниже).
"""

import io
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, QRect, QSize, Qt, QThreadPool
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from app import __version__  # noqa: E402
from app.core import applog, i18n
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer, _FillSaveTask, _FillSignals

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


def make_quad_img(path: str, w: int, h: int) -> None:
    """Картинка из четырёх цветных четвертей — удобно проверять пиксели."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    for y in range(h):
        for x in range(w):
            c = (QColor("#e02020") if x < w // 2 else QColor("#20b020")) \
                if y < h // 2 else (QColor("#2020e0") if x < w // 2 else QColor("#e0e000"))
            img.setPixelColor(x, y, c)
    assert img.save(path, "PNG")


def make_img(path: str, w: int, h: int, color: str) -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(path, "PNG")


def make_gif(path: str, w: int = 120, h: int = 90) -> None:
    """Валидный анимированный GIF — как в test_image_resize.py."""
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
    pm = viewer.view_label.pixmap()
    return pm is not None and not pm.isNull()


def wpt(view, ix: int, iy: int) -> QPointF:
    """Точка виджета, соответствующая пикселю картинки (ix, iy)."""
    r = view.pixmap_rect()
    iw, ih = view._crop_img.width(), view._crop_img.height()
    return QPointF(r.x() + ix * r.width() / iw, r.y() + iy * r.height() / ih)


def send_press(view, pos: QPointF, button: Qt.MouseButton) -> None:
    view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, button,
                                     button, Qt.NoModifier))


def send_move(view, pos: QPointF) -> None:
    view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, pos, Qt.NoButton,
                                    Qt.NoButton, Qt.NoModifier))


def send_release(view, pos: QPointF, button: Qt.MouseButton) -> None:
    view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, pos,
                                       button, Qt.NoButton, Qt.NoModifier))


def crop_drag(view, a, b) -> None:
    """Честная доставка событий мыши: press → move → release (в пикселях картинки)."""
    pa = wpt(view, *a) if isinstance(a, tuple) else a
    pb = wpt(view, *b) if isinstance(b, tuple) else b
    send_press(view, pa, Qt.MouseButton.LeftButton)
    send_move(view, pb)
    send_release(view, pb, Qt.MouseButton.LeftButton)


class _Loc:
    HomeLocation = 0
    PicturesLocation = 1
    GenericCacheLocation = 2


class FakeStdPaths:
    StandardLocation = _Loc

    @staticmethod
    def writableLocation(_kind) -> str:
        return tempfile.mkdtemp(prefix="ih_fl_home_")


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
    tmp = tempfile.mkdtemp(prefix="ih_fl_")
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

    # ---------- 1. свободное имя ----------
    names_dir = tempfile.mkdtemp(prefix="ih_fl_names_")
    check("имя: свободное «cat_fill.png»",
          lv._free_fill_name(names_dir, "cat", ".png") == "cat_fill.png")
    open(os.path.join(names_dir, "cat_fill.png"), "wb").close()
    check("имя: конфликт → «cat_fill-1.png»",
          lv._free_fill_name(names_dir, "cat", ".png") == "cat_fill-1.png")
    open(os.path.join(names_dir, "cat_fill-1.png"), "wb").close()
    check("имя: два конфликта → «cat_fill-2.png»",
          lv._free_fill_name(names_dir, "cat", ".png") == "cat_fill-2.png")

    # ---------- 2. задача записи напрямую ----------
    task_dir = tempfile.mkdtemp(prefix="ih_fl_task_")
    src_png = os.path.join(task_dir, "cat.png")
    make_quad_img(src_png, 400, 300)
    orig = QImage(src_png)
    # закрашиваем прямоугольник (100,50,250,200) оранжевым — как делает вьюер
    img = QImage(orig)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(QRect(100, 50, 250, 200), QColor("#ff8800"))
    p.end()
    sig = _FillSignals()
    results: list = []
    sig.done.connect(lambda *a: results.append(a))
    task = _FillSaveTask(img, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task, sig))
    QThreadPool.globalInstance().start(task)
    check("задача: файл записан и доложился",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is True
          and os.path.basename(results[0][1]) == "cat_fill.png",
          str(results))
    out = QImage(results[0][1]) if results else QImage()
    check("задача: размер результата = размеру оригинала 400×300",
          not out.isNull() and out.size() == QSize(400, 300),
          f"{out.width()}x{out.height()}" if not out.isNull() else "null")
    check("задача: закрашенный прямоугольник — цветом пипетки",
          not out.isNull()
          and out.pixelColor(100, 50) == QColor("#ff8800")
          and out.pixelColor(349, 249) == QColor("#ff8800")
          and out.pixelColor(224, 149) == QColor("#ff8800"),
          out.pixelColor(224, 149).name() if not out.isNull() else "null")
    check("задача: вне прямоугольника — пиксели оригинала",
          not out.isNull()
          and out.pixelColor(50, 25) == orig.pixelColor(50, 25)
          and out.pixelColor(380, 280) == orig.pixelColor(380, 280)
          and out.pixelColor(50, 280) == orig.pixelColor(50, 280),
          f"{out.pixelColor(50, 25).name()} vs {orig.pixelColor(50, 25).name()}"
          if not out.isNull() else "null")
    check("задача: оригинал на диске не тронут",
          QImage(src_png).pixelColor(224, 250) == QColor("#e0e000"))
    check("задача: событие в журнале",
          any("cat_fill.png" in ln and "cat.png" in ln for ln in log_lines),
          "\n".join(log_lines)[-200:] if log_lines else "журнал пуст")

    # конфликт имён в задаче
    results.clear()
    task2 = _FillSaveTask(img, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task2, sig))
    QThreadPool.globalInstance().start(task2)
    check("задача: конфликт имён → «cat_fill-1.png»",
          wait_until(app, lambda: len(results) == 1)
          and os.path.basename(results[0][1]) == "cat_fill-1.png", str(results))

    # JPEG из картинки с альфой: закрашенное остаётся, прозрачность белеет
    rgba = QImage(64, 48, QImage.Format.Format_ARGB32)
    rgba.fill(Qt.GlobalColor.transparent)
    p = QPainter(rgba)
    p.fillRect(QRect(0, 0, 32, 24), QColor("#ff8800"))
    p.end()
    task_dir2 = tempfile.mkdtemp(prefix="ih_fl_task2_")
    results.clear()
    task4 = _FillSaveTask(rgba, task_dir2, "alpha", ".jpg", "alpha.jpg", sig)
    _KEEP.append((task4, sig))
    QThreadPool.globalInstance().start(task4)
    check("задача: JPEG из картинки с альфой записался",
          wait_until(app, lambda: len(results) == 1) and results[0][0] is True,
          str(results))
    jpg = QImage(os.path.join(task_dir2, "alpha_fill.jpg"))
    check("задача: закрашенное в JPEG — цвет, прозрачность стала белой",
          not jpg.isNull() and jpg.pixelColor(8, 8) == QColor("#ff8800")
          and jpg.pixelColor(48, 40).value() > 200,
          f"{jpg.pixelColor(8, 8).name()}/{jpg.pixelColor(48, 40).name()}"
          if not jpg.isNull() else "null")

    # честная ошибка (папки нет)
    results.clear()
    task5 = _FillSaveTask(img, os.path.join(task_dir, "нет", "глубже"),
                          "cat", ".png", "cat.png", sig)
    _KEEP.append((task5, sig))
    QThreadPool.globalInstance().start(task5)
    check("задача: несуществующая папка — честная ошибка",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is False and results[0][4], str(results))

    # ---------- 3-6. живой вьюер ----------
    folder = tempfile.mkdtemp(prefix="ih_fl_imgs_")
    make_quad_img(os.path.join(folder, "cat.png"), 400, 300)
    make_img(os.path.join(folder, "dog.png"), 300, 200, "navy")
    make_img(os.path.join(folder, "bird.png"), 200, 150, "teal")
    make_gif(os.path.join(folder, "z_anim.gif"))   # «z_» — чтобы была последней

    viewer = LocalViewer()
    viewer.resize(1000, 720)
    viewer.show()
    viewer.load_folder(folder)
    ok = wait_until(app, lambda: viewer.list.count() == 4
                    and has_pixmap(viewer) and viewer.btn_picker.isEnabled())
    check("вьюер: папка открыта, картинка показана", ok)
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    ok = wait_until(app, lambda: viewer._pixmap is not None
                    and viewer._pixmap.size() == QSize(400, 300)
                    and viewer.btn_picker.isEnabled())
    check("вьюер: открыта плитка cat.png (400×300)", ok,
          viewer.list.currentItem().text() if viewer.list.currentItem() else "—")

    check("кнопка: «💧 Пипетка» на месте и checkable",
          hasattr(viewer, "btn_picker") and viewer.btn_picker.isCheckable())
    check("кнопка: включена для статичной картинки", viewer.btn_picker.isEnabled())
    check("кнопка: «🪣 Закрасить» скрыта вне режима обрезки",
          hasattr(viewer, "btn_fill") and not viewer.btn_fill.isVisible())
    check("образец: скрыт, пока цвет не взят",
          not viewer.picker_swatch.isVisible() and not viewer.picker_hex.isVisible())

    view = viewer.view_label

    # ---------- режим пипетки: наведение и клик ----------
    viewer.set_picker_mode(True)
    check("режим: пипетка включилась", viewer._picker_mode)
    check("режим: кнопка «💧 Пипетка» нажата", viewer.btn_picker.isChecked())
    check("режим: вью в режиме пипетки", view._picker_on)
    check("режим: статус с подсказкой", "💧" in viewer.status.text(),
          viewer.status.text())
    check("режим: источник цвета готов",
          viewer._picker_img is not None and viewer._picker_img.size() == QSize(400, 300))

    # наведение на красную четверть (50, 25) — статус показывает цвет
    send_move(view, wpt(view, 50, 25))
    hover_text = viewer.status.text()
    check("наведение: статус показывает «💧 #e02020 · 50,25»",
          "#e02020" in hover_text and "50,25" in hover_text, hover_text)

    # клик по зелёной четверти (300, 80) — цвет взят
    send_press(view, wpt(view, 300, 80), Qt.MouseButton.LeftButton)
    send_release(view, wpt(view, 300, 80), Qt.MouseButton.LeftButton)
    check("клик: цвет взят точно", viewer._picker_color == QColor("#20b020"),
          viewer._picker_color.name() if viewer._picker_color else "None")
    check("клик: буфер обмена получил HEX",
          QApplication.clipboard().text() == "#20b020",
          QApplication.clipboard().text())
    check("клик: статус «цвет в буфере»",
          "#20b020" in viewer.status.text() and "буфер" in viewer.status.text(),
          viewer.status.text())
    check("клик: образец появился на панели",
          viewer.picker_swatch.isVisible() and viewer.picker_hex.isVisible()
          and viewer.picker_hex.text() == "#20b020", viewer.picker_hex.text())

    # Esc закрывает режим пипетки; взятый цвет живёт
    viewer._escape_search()
    check("Esc: режим пипетки закрылся", not viewer._picker_mode)
    check("Esc: взятый цвет остался", viewer._picker_color == QColor("#20b020"))

    # ---------- правый клик берёт цвет БЕЗ режима ----------
    send_press(view, wpt(view, 50, 250), Qt.MouseButton.RightButton)
    send_release(view, wpt(view, 50, 250), Qt.MouseButton.RightButton)
    check("правый клик: цвет взят в обычном режиме",
          viewer._picker_color == QColor("#2020e0"),
          viewer._picker_color.name() if viewer._picker_color else "None")
    check("правый клик: буфер обновился",
          QApplication.clipboard().text() == "#2020e0",
          QApplication.clipboard().text())

    # ---------- закрашивание ----------
    # без выделения «🪣» ничего не делает
    viewer._on_fill_apply()
    check("закрасить: без выделения ничего не пишет",
          not os.path.lexists(os.path.join(folder, "cat_fill.png")))

    viewer.set_crop_mode(True)
    check("режим: обрезка включилась, «🪣 Закрасить» видна",
          viewer._crop_mode and viewer.btn_fill.isVisible())
    check("режим: пипетка закрылась обрезкой", not viewer._picker_mode)

    # правый клик в режиме обрезки — цвет берётся, выделение ещё не тронуто
    send_press(view, wpt(view, 50, 25), Qt.MouseButton.RightButton)
    send_release(view, wpt(view, 50, 25), Qt.MouseButton.RightButton)
    check("правый клик в обрезке: цвет взят",
          viewer._picker_color == QColor("#e02020"),
          viewer._picker_color.name() if viewer._picker_color else "None")

    # «Закрасить» без цвета (цвет ещё не взят на этой сессии? взят — сотрём)
    saved_color = viewer._picker_color
    viewer._picker_color = None
    crop_drag(view, (200, 100), (299, 149))
    viewer._on_fill_apply()
    check("закрасить: без цвета — честная подсказка, файла нет",
          "пипетк" in viewer.status.text()
          and not os.path.lexists(os.path.join(folder, "cat_fill.png")),
          viewer.status.text())
    viewer._picker_color = saved_color

    # выделение (200,100)-(299,149) уже стоит; клик «🪣 Закрасить»
    check("закрасить: выделение на месте и кнопка включена",
          view.selection() == QRect(200, 100, 100, 50) and viewer.btn_fill.isEnabled())
    viewer._on_fill_apply()
    fill_path = os.path.join(folder, "cat_fill.png")
    ok_saved = wait_until(app, lambda: os.path.lexists(fill_path)
                          and not viewer._fill_saving)
    check("закрасить: файл «cat_fill.png» записан", ok_saved)
    ok_strip = wait_until(app, lambda: (
        viewer.list.count() == 5
        and viewer.list.currentItem() is not None
        and viewer.list.currentItem().text() == "cat_fill.png"))
    check("закрасить: лента обновилась и открыла результат", ok_strip,
          f"count={viewer.list.count()}, cur="
          f"{viewer.list.currentItem().text() if viewer.list.currentItem() else None}")
    check("закрасить: статус называет файл",
          "cat_fill.png" in viewer.status.text(), viewer.status.text())
    check("закрасить: режим обрезки закрылся",
          wait_until(app, lambda: not viewer._crop_mode))
    out = QImage(fill_path)
    check("закрасить: в файле прямоугольник — цветом #e02020",
          not out.isNull() and out.size() == QSize(400, 300)
          and out.pixelColor(224, 120) == QColor("#e02020")
          and out.pixelColor(200, 100) == QColor("#e02020"),
          out.pixelColor(224, 120).name() if not out.isNull() else "null")
    check("закрасить: вне прямоугольника — пиксели оригинала",
          not out.isNull() and out.pixelColor(50, 25) == QColor("#e02020")
          and out.pixelColor(300, 80) == QColor("#20b020")
          and out.pixelColor(50, 250) == QColor("#2020e0"),
          out.pixelColor(300, 80).name() if not out.isNull() else "null")
    check("закрасить: оригинал на диске не тронут",
          QImage(os.path.join(folder, "cat.png")).pixelColor(224, 120)
          == QColor("#20b020"))
    check("закрасить: событие в журнале",
          any("cat.png" in ln and "cat_fill.png" in ln for ln in log_lines))

    # повторное закрашивание — без затираний
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(400, 300)
               and viewer.list.currentItem() is not None
               and viewer.list.currentItem().text() == "cat.png"
               and viewer.btn_crop.isEnabled())
    viewer.set_crop_mode(True)
    crop_drag(view, (10, 10), (59, 59))
    viewer._on_fill_apply()
    check("закрасить: повтор → «cat_fill-1.png», ничего не затёрто",
          wait_until(app, lambda: os.path.lexists(os.path.join(folder, "cat_fill-1.png")))
          and wait_until(app, lambda: not viewer._crop_mode))
    # лента пересканировалась, результат открылся и ДОГРУЗИЛСЯ (пиксмап на
    # месте, кнопки ожили) — иначе режимы честно не включаются на пустом показе
    wait_until(app, lambda: viewer.list.count() == 6
               and viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(400, 300)
               and viewer.btn_picker.isEnabled()
               and viewer.list.currentItem() is not None
               and viewer.list.currentItem().text() == "cat_fill-1.png")

    # ---------- 7. границы и выходы ----------
    # взаимоисключающие режимы
    viewer.set_picker_mode(True)
    viewer.set_crop_mode(True)
    check("режимы: вход в «✂ Обрезать» закрыл пипетку",
          not viewer._picker_mode and viewer._crop_mode)
    viewer.set_picker_mode(True)
    check("режимы: вход в пипетку закрыл обрезку",
          viewer._picker_mode and not viewer._crop_mode)
    viewer.set_resize_mode(True)
    check("режимы: вход в «⇲ Размер» закрыл пипетку",
          not viewer._picker_mode and viewer._resize_mode)
    viewer.set_resize_mode(False)

    # смена картинки закрывает пипетку
    viewer.set_picker_mode(True)
    viewer.list.setCurrentRow(row_of(viewer, "dog.png"))
    check("смена картинки: пипетка закрылась",
          wait_until(app, lambda: not viewer._picker_mode))
    check("смена картинки: новая картинка загрузилась",
          wait_until(app, lambda: viewer._pixmap is not None
                     and viewer._pixmap.size() == QSize(300, 200)))
    check("смена картинки: кнопка снова включена", viewer.btn_picker.isEnabled())
    check("смена картинки: взятый цвет пережил смену",
          viewer._picker_color == QColor("#e02020"))

    # ---------- GIF ----------
    viewer.list.setCurrentRow(row_of(viewer, "z_anim.gif"))
    check("GIF: анимация открылась",
          wait_until(app, lambda: viewer._movie is not None))
    check("GIF: кнопка «💧 Пипетка» погашена", not viewer.btn_picker.isEnabled())
    viewer.btn_picker.setEnabled(True)   # «упрямый» клик всё равно не включит режим
    viewer.btn_picker.toggled.emit(True)
    check("GIF: режим не включается", not viewer._picker_mode)
    viewer.btn_picker.setEnabled(False)

    # ---------- пустой просмотр ----------
    viewer.load_folder(tempfile.mkdtemp(prefix="ih_fl_empty_"))
    wait_until(app, lambda: viewer.list.count() == 0)
    check("пусто: кнопка погашена", not viewer.btn_picker.isEnabled())

    # ---------- 8. локализация ----------
    viewer.load_folder(folder)
    wait_until(app, lambda: viewer.list.count() == 6
               and viewer.btn_picker.isEnabled())
    i18n.set_lang("en", persist=False)
    check("en: текст кнопки", viewer.btn_picker.text() == "💧 Picker",
          viewer.btn_picker.text())
    check("en: подсказка обновилась",
          "right-click" in viewer.btn_picker.toolTip().lower(),
          viewer.btn_picker.toolTip()[:60])
    check("en: «🪣 Fill»", viewer.btn_fill.text() == "🪣 Fill",
          viewer.btn_fill.text())
    i18n.set_lang("zh", persist=False)
    check("zh: текст кнопки", viewer.btn_picker.text() == "💧 取色器",
          viewer.btn_picker.text())
    check("zh: «🪣 填充»", viewer.btn_fill.text() == "🪣 填充",
          viewer.btn_fill.text())
    i18n.set_lang("ru", persist=False)
    check("ru: текст кнопки вернулся", viewer.btn_picker.text() == "💧 Пипетка",
          viewer.btn_picker.text())
    check("ru: «🪣 Закрасить» вернулась", viewer.btn_fill.text() == "🪣 Закрасить",
          viewer.btn_fill.text())

    # ---------- 9. смоук ----------
    check("версия 0.8.13", __version__ == "0.8.13", __version__)

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
