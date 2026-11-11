"""Оффлайн-тест обрезки картинки мышью, как в XnView (v0.8.7).

Пожелание: «я ошибся, нужна функция "обрезать" как в xnview» — выделение
рамкой с рукоятками в окне предпросмотра и кнопки «Обрезать» / «Сохранить
выделенную область как...» / «Обрезать, Сохранить и перейти к следующему».

Проверяет:
1. свободное имя «имя_crop.ext» с суффиксами -1, -2 при конфликте;
2. задачу записи напрямую: файл ровно выделенной области (пиксели совпадают
   с исходником), оригинал цел, журнал, конфликт имён, явный путь «Как…»
   (без расширения — добавляется), JPEG из картинки с альфой (белый фон),
   честная ошибка;
3. живой вьюер: кнопки на тулбаре, вход в режим, три кнопки видны только
   в режиме и гаснут без выделения;
4. выделение честной доставкой событий мыши: резинка от нажатия до
   отпускания, случайный клик выделения не оставляет;
5. рукоятки: crop_handle_at на углах/краях и мимо, перетаскивание угла
   меняет рамку, перенос рамки целиком, статус «✂ W×H из W×H»;
6. зум в режиме работает, выделение (в координатах картинки) переживает
   зум и «◱ Вписать»;
7. сохранение из режима: файл на диске, лента обновилась и открыла
   результат, режим закрылся, повтор — без затираний;
8. «💾 Как…» с подменённым диалогом — файл ровно по выбранному пути;
9. серия «✂▶ К следующему»: сохраняет и сама открывает следующую картинку
   с рамкой наготове, на последней честно заканчивается;
10. Esc закрывает режим; зум/«◱» выделение не ломают; смена картинки и
    смена папки закрывают; GIF и пустой просмотр — кнопка погашена;
    режимы «⇲ Размер» и «✂ Обрезать» взаимоисключающие;
11. локализация ru/en/zh новых кнопок;
12. смоук: версия 0.8.16.

Запуск: LD_LIBRARY_PATH=… .venv/bin/python scripts/test_image_crop.py
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
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from app import __version__  # noqa: E402
from app.core import applog, i18n
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer, _CropSaveTask, _CropSignals, _ResizeView

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


def wpt(view: _ResizeView, ix: int, iy: int) -> QPointF:
    """Точка виджета, соответствующая пикселю картинки (ix, iy)."""
    r = view.pixmap_rect()
    iw, ih = view._crop_img.width(), view._crop_img.height()
    return QPointF(r.x() + ix * r.width() / iw, r.y() + iy * r.height() / ih)


def crop_drag(view: _ResizeView, a, b) -> None:
    """Честная доставка событий мыши: press → move → release (в пикселях картинки)."""
    pa = wpt(view, *a) if isinstance(a, tuple) else a
    pb = wpt(view, *b) if isinstance(b, tuple) else b
    view.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pa,
                                     Qt.MouseButton.LeftButton,
                                     Qt.MouseButton.LeftButton, Qt.NoModifier))
    view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, pb,
                                    Qt.NoButton, Qt.MouseButton.LeftButton,
                                    Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease,
                                       pb, Qt.MouseButton.LeftButton,
                                       Qt.NoButton, Qt.NoModifier))


class _Loc:
    HomeLocation = 0
    PicturesLocation = 1
    GenericCacheLocation = 2


class FakeStdPaths:
    StandardLocation = _Loc

    @staticmethod
    def writableLocation(_kind) -> str:
        return tempfile.mkdtemp(prefix="ih_cr_home_")


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
    tmp = tempfile.mkdtemp(prefix="ih_cr_")
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
    names_dir = tempfile.mkdtemp(prefix="ih_cr_names_")
    check("имя: свободное «cat_crop.png»",
          lv._free_crop_name(names_dir, "cat", ".png") == "cat_crop.png")
    open(os.path.join(names_dir, "cat_crop.png"), "wb").close()
    check("имя: конфликт → «cat_crop-1.png»",
          lv._free_crop_name(names_dir, "cat", ".png") == "cat_crop-1.png")
    open(os.path.join(names_dir, "cat_crop-1.png"), "wb").close()
    check("имя: два конфликта → «cat_crop-2.png»",
          lv._free_crop_name(names_dir, "cat", ".png") == "cat_crop-2.png")

    # ---------- 2. задача записи напрямую ----------
    task_dir = tempfile.mkdtemp(prefix="ih_cr_task_")
    src_png = os.path.join(task_dir, "cat.png")
    make_quad_img(src_png, 400, 300)
    img = QImage(src_png)
    sig = _CropSignals()
    results: list = []
    sig.done.connect(lambda *a: results.append(a))
    rect = QRect(100, 50, 250, 200)
    task = _CropSaveTask(img, rect, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task, sig))
    QThreadPool.globalInstance().start(task)
    check("задача: файл записан и доложился",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is True
          and os.path.basename(results[0][1]) == "cat_crop.png",
          str(results))
    out = QImage(results[0][1]) if results else QImage()
    check("задача: размер результата ровно 250×200",
          not out.isNull() and out.size() == QSize(250, 200),
          f"{out.width()}x{out.height()}" if not out.isNull() else "null")
    check("задача: пиксели совпадают с исходником (углы выделения)",
          not out.isNull()
          and out.pixelColor(0, 0) == img.pixelColor(100, 50)
          and out.pixelColor(249, 199) == img.pixelColor(349, 249),
          f"{out.pixelColor(0, 0).name()} vs {img.pixelColor(100, 50).name()}"
          if not out.isNull() else "null")
    check("задача: оригинал не тронут",
          QImage(src_png).size() == QSize(400, 300))
    check("задача: событие в журнале",
          any("cat_crop.png" in ln and "cat.png" in ln for ln in log_lines),
          "\n".join(log_lines)[-200:] if log_lines else "журнал пуст")

    # конфликт имён в задаче
    results.clear()
    task2 = _CropSaveTask(img, rect, task_dir, "cat", ".png", "cat.png", sig)
    _KEEP.append((task2, sig))
    QThreadPool.globalInstance().start(task2)
    check("задача: конфликт имён → «cat_crop-1.png»",
          wait_until(app, lambda: len(results) == 1)
          and os.path.basename(results[0][1]) == "cat_crop-1.png", str(results))

    # «💾 Как…»: явный путь в другой папке, без расширения — добавится .png
    as_dir = tempfile.mkdtemp(prefix="ih_cr_as_")
    results.clear()
    task3 = _CropSaveTask(img, rect, task_dir, "cat", ".png", "cat.png", sig,
                          os.path.join(as_dir, "picked"))
    _KEEP.append((task3, sig))
    QThreadPool.globalInstance().start(task3)
    picked = os.path.join(as_dir, "picked.png")
    check("задача: «Как…» без расширения → «picked.png» по выбранному пути",
          wait_until(app, lambda: len(results) == 1) and results[0][0] is True
          and os.path.lexists(picked), str(results))

    # JPEG из картинки с альфой — белый фон вместо чёрной прозрачности
    rgba = QImage(64, 48, QImage.Format.Format_ARGB32)
    rgba.fill(Qt.GlobalColor.transparent)
    task_dir2 = tempfile.mkdtemp(prefix="ih_cr_task2_")
    results.clear()
    task4 = _CropSaveTask(rgba, QRect(0, 0, 32, 24), task_dir2, "alpha", ".jpg",
                          "alpha.jpg", sig)
    _KEEP.append((task4, sig))
    QThreadPool.globalInstance().start(task4)
    check("задача: JPEG из картинки с альфой записался",
          wait_until(app, lambda: len(results) == 1) and results[0][0] is True,
          str(results))
    jpg = QImage(os.path.join(task_dir2, "alpha_crop.jpg"))
    check("задача: прозрачность JPEG стала белой, а не чёрной",
          not jpg.isNull() and jpg.pixelColor(0, 0).value() > 200,
          jpg.pixelColor(0, 0).name() if not jpg.isNull() else "null")

    # честная ошибка (папки нет)
    results.clear()
    task5 = _CropSaveTask(img, rect, os.path.join(task_dir, "нет", "глубже"),
                          "cat", ".png", "cat.png", sig)
    _KEEP.append((task5, sig))
    QThreadPool.globalInstance().start(task5)
    check("задача: несуществующая папка — честная ошибка",
          wait_until(app, lambda: len(results) == 1)
          and results[0][0] is False and results[0][4], str(results))

    # ---------- 3-7. живой вьюер ----------
    folder = tempfile.mkdtemp(prefix="ih_cr_imgs_")
    make_quad_img(os.path.join(folder, "cat.png"), 400, 300)
    make_img(os.path.join(folder, "dog.png"), 300, 200, "navy")
    make_img(os.path.join(folder, "bird.png"), 200, 150, "teal")
    make_gif(os.path.join(folder, "z_anim.gif"))   # «z_» — чтобы была последней

    viewer = LocalViewer()
    viewer.resize(1000, 720)
    viewer.show()
    viewer.load_folder(folder)
    ok = wait_until(app, lambda: viewer.list.count() == 4
                    and has_pixmap(viewer) and viewer.btn_crop.isEnabled())
    check("вьюер: папка открыта, картинка показана", ok)
    # в ленте порядок натуральный: bird.png первый — открываем cat.png явно
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    ok = wait_until(app, lambda: viewer._pixmap is not None
                    and viewer._pixmap.size() == QSize(400, 300)
                    and viewer.btn_crop.isEnabled())
    check("вьюер: открыта плитка cat.png (400×300)", ok,
          viewer.list.currentItem().text() if viewer.list.currentItem() else "—")

    check("кнопка: «✂ Обрезать» на месте и checkable",
          hasattr(viewer, "btn_crop") and viewer.btn_crop.isCheckable())
    check("кнопка: включена для статичной картинки", viewer.btn_crop.isEnabled())
    check("кнопки: три кнопки режима скрыты вне режима",
          not viewer.btn_crop_save.isVisible()
          and not viewer.btn_crop_saveas.isVisible()
          and not viewer.btn_crop_next.isVisible())

    # вход в режим
    viewer.set_crop_mode(True)
    check("режим: включился", viewer._crop_mode)
    check("режим: кнопка «✂ Обрезать» нажата", viewer.btn_crop.isChecked())
    check("режим: три кнопки видны и погашены (выделения нет)",
          viewer.btn_crop_save.isVisible() and viewer.btn_crop_saveas.isVisible()
          and viewer.btn_crop_next.isVisible()
          and not viewer.btn_crop_save.isEnabled()
          and not viewer.btn_crop_next.isEnabled())
    check("режим: статус с подсказкой", "✂" in viewer.status.text(),
          viewer.status.text())
    check("режим: вью в режиме обрезки", viewer.view_label._crop_on)
    check("режим: картинке известен размер 400×300",
          viewer.view_label._crop_img == QSize(400, 300),
          str(viewer.view_label._crop_img))

    view = viewer.view_label

    # «Сохранить» без выделения — ничего не делает
    viewer._on_crop_apply()
    check("без выделения: «Сохранить» ничего не пишет",
          not os.path.lexists(os.path.join(folder, "cat_crop.png")))

    # выделение резинкой: (100,50) → (349,249) = 250×200
    crop_drag(view, (100, 50), (349, 249))
    check("выделение: рамка ровно 250×200 в координатах картинки",
          view.selection() == QRect(100, 50, 250, 200), str(view.selection()))
    check("выделение: статус «✂ 250×200 из 400×300»",
          "250×200" in viewer.status.text() and "400×300" in viewer.status.text(),
          viewer.status.text())
    check("выделение: кнопки включились",
          viewer.btn_crop_save.isEnabled() and viewer.btn_crop_next.isEnabled())

    # случайный клик (без движения) сбрасывает выделение
    crop_drag(view, (30, 30), (30, 30))
    check("клик: выделение сброшено, кнопки погашены",
          view.selection().isNull() and not viewer.btn_crop_save.isEnabled())

    # рукоятки: crop_handle_at
    crop_drag(view, (100, 50), (349, 249))   # снова рамка 250×200
    s = view.selection()
    check("рукоятки: левый-верхний угол найден",
          view.crop_handle_at(wpt(view, s.left(), s.top()).toPoint())
          == _ResizeView.CROP_TL)
    check("рукоятки: правый-нижний угол найден",
          view.crop_handle_at(wpt(view, s.right(), s.bottom()).toPoint())
          == _ResizeView.CROP_BR)
    check("рукоятки: правый край найден",
          view.crop_handle_at(wpt(view, s.right(),
                                  (s.top() + s.bottom()) // 2).toPoint())
          == _ResizeView.CROP_R)
    check("рукоятки: центр рамки — не рукоятка",
          view.crop_handle_at(wpt(view, (s.left() + s.right()) // 2,
                                  (s.top() + s.bottom()) // 2).toPoint())
          == _ResizeView.CROP_NONE)
    check("рукоятки: мимо картинки — не рукоятка",
          view.crop_handle_at(QPoint(0, 0)) == _ResizeView.CROP_NONE)

    # тянем угол: рамка растягивается до (100,50)-(449,399)... за край нельзя
    crop_drag(view, wpt(view, s.right(), s.bottom()),
              wpt(view, 380, 280))   # правый-нижний угол внутрь
    s2 = view.selection()
    check("драг угла: рамка уменьшилась до (100,50,281,231)",
          s2 == QRect(100, 50, 281, 231), str(s2))

    # перенос рамки целиком: схватить в центре, сдвинуть на (20, 10)
    center = ((s2.left() + s2.right()) // 2, (s2.top() + s2.bottom()) // 2)
    crop_drag(view, wpt(view, *center),
              wpt(view, center[0] + 20, center[1] + 10))
    s3 = view.selection()
    check("перенос рамки: сдвиг на (20, 10), размер тот же",
          abs(s3.x() - (s2.x() + 20)) <= 1 and s3.y() == s2.y() + 10
          and s3.size() == s2.size(), str(s3))

    # рамка у края: перенос за предел картинки зажимается
    cx, cy = s3.center().x(), s3.center().y()
    crop_drag(view, wpt(view, cx, cy), wpt(view, cx + 1000, cy))
    s4 = view.selection()
    check("перенос за край: рамка зажата у правого края картинки",
          s4.size() == s3.size() and s4.y() == s3.y()
          and s4.right() >= 398, str(s4))

    # зум в режиме работает, выделение в координатах картинки не меняется
    sel_before = QRect(view.selection())
    viewer.zoom(1.25)
    check("зум в режиме обрезки работает", viewer._mode == "manual")
    check("зум: выделение (координаты картинки) не изменилось",
          view.selection() == sel_before, str(view.selection()))
    viewer.fit_to_window()
    check("«◱»: показ вписан, режим и выделение живы",
          viewer._crop_mode and viewer._mode == "fit"
          and view.selection() == sel_before)

    # отрисовка рамки/рукояток/сетки/бейджа не падает
    ok_paint = True
    try:
        canvas = QImage(900, 700, QImage.Format.Format_RGB32)
        canvas.fill(Qt.GlobalColor.darkGray)
        view.render(canvas)
    except Exception as exc:            # noqa: BLE001
        ok_paint = False
        print("    paint error:", exc)
    check("отрисовка: рамка с рукоятками, сеткой и бейджем — без ошибок", ok_paint)

    # сохранение из режима (в статусе может быть и имя файла, и «1 из N» —
    # после ленты открывается результат); рамка — снова ровно (100,50,250,200)
    crop_drag(view, (100, 50), (349, 249))
    viewer._on_crop_apply()
    saved_path = os.path.join(folder, "cat_crop.png")
    ok_saved = wait_until(app, lambda: os.path.lexists(saved_path))
    check("сохранение: файл «cat_crop.png» появился", ok_saved)
    ok_strip = wait_until(app, lambda: (
        viewer.list.count() == 5
        and viewer.list.currentItem() is not None
        and viewer.list.currentItem().text() == "cat_crop.png"))
    check("сохранение: лента обновилась и открыла новый файл", ok_strip,
          f"count={viewer.list.count()}, cur="
          f"{viewer.list.currentItem().text() if viewer.list.currentItem() else None}")
    check("сохранение: статус называет сохранённый файл",
          "cat_crop.png" in viewer.status.text(), viewer.status.text())
    check("сохранение: оригинал не тронут",
          QImage(os.path.join(folder, "cat.png")).size() == QSize(400, 300))
    check("сохранение: режим закрылся",
          wait_until(app, lambda: not viewer._crop_mode))
    out = QImage(saved_path)
    check("сохранение: размер файла ровно 250×200, пиксели из выделения",
          out.size() == QSize(250, 200)
          and out.pixelColor(0, 0) == QColor("#e02020"),
          f"{out.width()}x{out.height()}" if not out.isNull() else "null")

    # повторное сохранение той же области — без затираний
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(400, 300))
    viewer.set_crop_mode(True)
    crop_drag(view, (100, 50), (349, 249))
    viewer._on_crop_apply()
    dup_path = os.path.join(folder, "cat_crop-1.png")
    check("сохранение: повтор → «cat_crop-1.png», ничего не затёрто",
          wait_until(app, lambda: os.path.lexists(dup_path))
          and wait_until(app, lambda: not viewer._crop_mode))
    wait_until(app, lambda: viewer.list.count() == 6)

    # «💾 Как…» с подменённым диалогом
    lv.QFileDialog.getSaveFileName = staticmethod(
        lambda *a, **k: (os.path.join(as_dir, "chosen"), "-filter-"))
    viewer.list.setCurrentRow(row_of(viewer, "cat.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(400, 300))
    viewer.set_crop_mode(True)
    crop_drag(view, (10, 10), (109, 59))
    viewer._on_crop_save_as()
    chosen = os.path.join(as_dir, "chosen.png")
    check("«Как…»: файл по пути из диалога, расширение добавлено",
          wait_until(app, lambda: os.path.lexists(chosen))
          and wait_until(app, lambda: not viewer._crop_mode))
    del lv.QFileDialog.getSaveFileName   # убрать подмену

    # ---------- 8-9. серия «✂▶ К следующему» ----------
    folder3 = tempfile.mkdtemp(prefix="ih_cr_seq_")
    make_img(os.path.join(folder3, "1.png"), 400, 300, "#111111")
    make_img(os.path.join(folder3, "2.png"), 400, 300, "#222222")
    make_img(os.path.join(folder3, "3.png"), 400, 300, "#333333")
    viewer.load_folder(folder3)
    ok = wait_until(app, lambda: viewer.list.count() == 3
                    and viewer._pixmap is not None
                    and viewer.list.currentItem() is not None
                    and viewer.list.currentItem().text() == "1.png")
    check("серия: папка из трёх открыта, активна «1.png»", ok)

    viewer.set_crop_mode(True)
    crop_drag(view, (10, 10), (209, 159))
    viewer.btn_crop_next.click()
    ok = wait_until(app, lambda: os.path.lexists(os.path.join(folder3, "1_crop.png"))
                    and viewer.list.currentItem() is not None
                    and viewer.list.currentItem().text() == "2.png"
                    and viewer._crop_mode)
    check("серия: «1_crop.png» записан, открылась «2.png», режим жив", ok,
          f"cur={viewer.list.currentItem().text() if viewer.list.currentItem() else None}, "
          f"mode={viewer._crop_mode}")
    check("серия: событие в журнале",
          any("1.png" in ln and "1_crop.png" in ln for ln in log_lines))

    # рамка на новой картинке чистая — выделить и снова «К следующему»
    check("серия: выделение на новой картинке пустое",
          view.selection().isNull())
    crop_drag(view, (20, 20), (219, 169))
    viewer.btn_crop_next.click()
    ok = wait_until(app, lambda: os.path.lexists(os.path.join(folder3, "2_crop.png"))
                    and viewer.list.currentItem() is not None
                    and viewer.list.currentItem().text() == "3.png"
                    and viewer._crop_mode)
    check("серия: «2_crop.png» записан, открылась «3.png»", ok)

    # последняя картинка: серия честно заканчивается
    crop_drag(view, (30, 30), (229, 179))
    viewer.btn_crop_next.click()
    ok = wait_until(app, lambda: os.path.lexists(os.path.join(folder3, "3_crop.png"))
                    and not viewer._crop_continue
                    and not viewer._crop_mode
                    and viewer.list.currentItem() is not None
                    and viewer.list.currentItem().text() == "3_crop.png")
    check("серия: «3_crop.png» записан, серия закрылась, открыт результат", ok,
          f"cur={viewer.list.currentItem().text() if viewer.list.currentItem() else None}, "
          f"mode={viewer._crop_mode}, cont={viewer._crop_continue}")
    check("серия: в журнале все три события",
          sum(1 for ln in log_lines
              if "Обрезана картинка" in ln and ("_crop.png" in ln)) >= 3,
          str(sum(1 for ln in log_lines
                  if "Обрезана картинка" in ln and ("_crop.png" in ln))))

    # ---------- 10. выходы и границы ----------
    viewer.list.setCurrentRow(row_of(viewer, "1.png"))
    wait_until(app, lambda: viewer._pixmap is not None
               and viewer._pixmap.size() == QSize(400, 300))
    viewer.set_crop_mode(True)
    crop_drag(view, (10, 10), (109, 59))
    viewer._escape_search()
    check("Esc: режим закрылся", not viewer._crop_mode)

    # взаимоисключающие режимы
    viewer.set_crop_mode(True)
    viewer.set_resize_mode(True)
    check("режимы: вход в «⇲ Размер» закрыл обрезку",
          not viewer._crop_mode and viewer._resize_mode)
    viewer.set_resize_mode(False)
    viewer.set_crop_mode(True)
    viewer.btn_resize.toggled.emit(True)   # клик по «⇲ Размер»
    check("режимы: вход в ресайс кнопкой закрыл обрезку",
          not viewer._crop_mode and viewer._resize_mode)
    viewer.set_resize_mode(False)

    # смена картинки закрывает режим
    viewer.set_crop_mode(True)
    viewer.list.setCurrentRow(row_of(viewer, "2.png"))
    check("смена картинки: режим закрылся",
          wait_until(app, lambda: not viewer._crop_mode))
    check("смена картинки: новая картинка загрузилась",
          wait_until(app, lambda: viewer._pixmap is not None
                     and viewer._pixmap.size() == QSize(400, 300)))
    check("смена картинки: кнопка снова включена", viewer.btn_crop.isEnabled())

    # ---------- GIF ----------
    viewer.load_folder(folder)
    wait_until(app, lambda: viewer.list.count() == 6
               and viewer._pixmap is not None
               and viewer.btn_crop.isEnabled())
    viewer.list.setCurrentRow(row_of(viewer, "z_anim.gif"))
    check("GIF: анимация открылась",
          wait_until(app, lambda: viewer._movie is not None))
    check("GIF: кнопка «✂ Обрезать» погашена", not viewer.btn_crop.isEnabled())
    viewer.btn_crop.setEnabled(True)   # «упрямый» клик всё равно не включит режим
    viewer.btn_crop.toggled.emit(True)
    check("GIF: режим не включается", not viewer._crop_mode)
    viewer.btn_crop.setEnabled(False)

    # ---------- пустой просмотр ----------
    viewer.load_folder(tempfile.mkdtemp(prefix="ih_cr_empty_"))
    wait_until(app, lambda: viewer.list.count() == 0)
    check("пусто: кнопка погашена", not viewer.btn_crop.isEnabled())

    # ---------- смена папки закрывает серию ----------
    viewer.load_folder(folder3)
    wait_until(app, lambda: viewer.list.count() == 6
               and viewer.btn_crop.isEnabled())
    viewer.set_crop_mode(True)
    crop_drag(view, (10, 10), (109, 59))
    viewer._crop_continue = True   # как после «К следующему»
    viewer.list.setCurrentRow(row_of(viewer, "2.png"))
    # флаг серии гасится при приходе новой картинки — ждём именно этого
    ok = wait_until(app, lambda: not viewer._crop_continue)
    check("смена картинки вручную: серия погашена", ok)

    # ---------- 11. локализация ----------
    viewer.load_folder(folder3)
    wait_until(app, lambda: viewer.list.count() == 6
               and viewer.btn_crop.isEnabled())
    i18n.set_lang("en", persist=False)
    check("en: текст кнопки", viewer.btn_crop.text() == "✂ Crop",
          viewer.btn_crop.text())
    check("en: подсказка обновилась",
          "xnview" in viewer.btn_crop.toolTip().lower()
          or "drag" in viewer.btn_crop.toolTip().lower(),
          viewer.btn_crop.toolTip()[:60])
    check("en: «💾 Сохранить»", viewer.btn_crop_save.text() == "💾 Save",
          viewer.btn_crop_save.text())
    check("en: «✂▶ Save & next»", viewer.btn_crop_next.text() == "✂▶ Save & next",
          viewer.btn_crop_next.text())
    i18n.set_lang("zh", persist=False)
    check("zh: текст кнопки", viewer.btn_crop.text() == "✂ 裁剪",
          viewer.btn_crop.text())
    i18n.set_lang("ru", persist=False)
    check("ru: текст кнопки вернулся", viewer.btn_crop.text() == "✂ Обрезать",
          viewer.btn_crop.text())

    # ---------- 12. смоук ----------
    check("версия 0.8.16", __version__ == "0.8.16", __version__)

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
