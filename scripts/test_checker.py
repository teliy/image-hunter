"""Оффлайн-тест фона-«шахматки» под прозрачными картинками (v0.8.1).

Пожелание: «пусть фоном для прозрачных форматов будет регулируемая по
размеру ползунком сетка из серых и белых квадратов».

Проверяет:
1. плитку «шахматки»: 2×2 клетки, белый и серый по диагонали;
2. HiDPI: плитка рисуется в физических пикселях (cell × dpr) с dpr-меткой;
3. иконку-шахматку у ползунка (те же цвета);
4. отрисовку _CheckerView: прозрачный пиксель картинки показывает квадрат,
   непрозрачный закрывает его; без плитки — обычный QLabel;
5. включение шахматки по альфа-каналу: прозрачный PNG → включена,
   JPEG → выключена (сквозной путь _show_index → _on_view_ready);
6. текст («Откройте папку…», ошибки) всегда без шахматки;
7. ползунок: пределы 4–32, значение запоминается в QSettings,
   при видимой шахматке плитка перестраивается под новую клетку;
8. новые экземпляры вьюера читают клетку из настроек;
9. превью выбора после удаления фона (_checker_pixmap) рисует клеткой
   из настроек;
10. смоук: версия 0.8.16.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_checker.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui.local_viewer import (  # noqa: E402
    CHECKER_DEFAULT, CHECKER_MAX, CHECKER_MIN,
    LocalViewer, _CheckerView, _checker_cell_setting, _checker_tile,
    _mini_checker_icon, _checker_pixmap,
)

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


def wait_until(cond, timeout_ms: int = 15000, what: str = "") -> bool:
    deadline = time.time() + timeout_ms / 1000
    app = QApplication.instance()
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    print(f"    ... не дождались: {what}")
    return False


def rgb(img: QImage, x: int, y: int) -> QColor:
    return QColor(img.pixelColor(QPoint(x, y)))


def make_transparent_png(path: str, size: int = 40) -> None:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(0)   # полностью прозрачная
    img.save(path, "PNG")


def make_opaque_jpg(path: str, size: int = 40) -> None:
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor("#ff0000"))
    img.save(path, "JPG")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    settings = QSettings("ImageHunter", "ImageHunter")
    settings.setValue("viewer/checker_cell", CHECKER_DEFAULT)
    settings.setValue("viewer/thumbs", False)
    settings.setValue("viewer/last_folder", "")
    settings.setValue("viewer/last_query", "")

    # ---------- 1–3: плитка, HiDPI, иконка ----------
    tile = _checker_tile(10, 1.0)
    check("плитка 2×2 клетки", tile.width() == 20 and tile.height() == 20,
          f"{tile.width()}x{tile.height()}")
    check("плитка: левый верх белый", rgb(tile.toImage(), 5, 5) == QColor("#ffffff"))
    check("плитка: правый верх серый", rgb(tile.toImage(), 15, 5) == QColor("#c0c0c0"))
    check("плитка: левый низ серый", rgb(tile.toImage(), 5, 15) == QColor("#c0c0c0"))
    check("плитка: правый низ белый", rgb(tile.toImage(), 15, 15) == QColor("#ffffff"))

    tile2 = _checker_tile(10, 2.0)
    check("HiDPI: физический размер ×2",
          tile2.width() == 40 and tile2.devicePixelRatio() == 2.0,
          f"{tile2.width()}x{tile2.height()} dpr={tile2.devicePixelRatio()}")
    check("HiDPI: клетка 20 физических пикселей",
          rgb(tile2.toImage(), 30, 10) == QColor("#c0c0c0"))

    icon = _mini_checker_icon()
    check("иконка 16×16", icon.width() == 16 and icon.height() == 16)
    check("иконка: белый квадрат", rgb(icon.toImage(), 2, 2) == QColor("#ffffff"))
    check("иконка: серый квадрат", rgb(icon.toImage(), 14, 2) == QColor("#c0c0c0"))

    # ---------- 4: _CheckerView рисует плитку под прозрачным пикселем ----------
    view = _CheckerView()
    view.setFixedSize(40, 40)
    trans = QImage(40, 40, QImage.Format.Format_ARGB32)
    trans.fill(0)
    view.setPixmap(QPixmap.fromImage(trans))
    view.set_checker_tile(_checker_tile(10, 1.0))
    grabbed = view.grab().toImage()
    check("просмотр: прозрачный пиксель показывает белый квадрат",
          rgb(grabbed, 5, 5) == QColor("#ffffff"))
    check("просмотр: прозрачный пиксель показывает серый квадрат",
          rgb(grabbed, 15, 5) == QColor("#c0c0c0"))
    # непрозрачный пиксель закрывает квадраты (QLabel рисует 20×20 pixmap
    # по вертикальному центру: зона (0..20, 10..30))
    opaque_pm = QPixmap(20, 20)
    opaque_pm.fill(QColor("#123456"))
    view.setPixmap(opaque_pm)
    view.set_checker_tile(_checker_tile(10, 1.0))
    grabbed2 = view.grab().toImage()
    check("просмотр: непрозрачная картинка закрывает квадраты",
          rgb(grabbed2, 5, 15) == QColor("#123456"), str(rgb(grabbed2, 5, 15).name()))

    view.set_checker_tile(None)
    grabbed3 = view.grab().toImage()
    check("просмотр: без плитки квадратов нет",
          rgb(grabbed3, 5, 5) != QColor("#ffffff") or rgb(grabbed3, 5, 5) != QColor("#c0c0c0"),
          str(rgb(grabbed3, 5, 5).name()))

    # ---------- 5–8: вьюер целиком ----------
    tmp = tempfile.mkdtemp(prefix="ih_checker_")
    png = os.path.join(tmp, "trans.png")
    jpg = os.path.join(tmp, "opaque.jpg")
    make_transparent_png(png)
    make_opaque_jpg(jpg)

    viewer = LocalViewer()
    viewer.resize(1200, 700)
    viewer.load_folder(tmp)   # скан папки в рабочем потоке
    pump(app, 200)
    wait_until(lambda: len(viewer._paths) >= 2, what="лента папки")
    row_png = viewer._paths.index(png)
    row_jpg = viewer._paths.index(jpg)

    viewer._show_index(row_png)
    wait_until(lambda: viewer._pixmap is not None and not viewer._view_inflight,
               what="PNG прочитан")
    pump(app, 100)
    check("PNG с альфа-каналом: шахматка включена",
          viewer._checker_on and viewer.view_label._tile is not None)
    tile_logical = viewer.view_label._tile.width() / viewer.view_label._tile.devicePixelRatio()
    check("шахматка: клетка из настроек (10)",
          tile_logical == CHECKER_DEFAULT * 2, f"tile={tile_logical}")

    # ползунок: перестраивает видимую плитку и запоминается
    viewer.checker_slider.setValue(16)
    check("ползунок: клетка 16", viewer._checker_cell == 16)
    check("ползунок: настройки запомнены",
          settings.value("viewer/checker_cell", type=int) == 16)
    tile_logical = viewer.view_label._tile.width() / viewer.view_label._tile.devicePixelRatio()
    check("ползунок: видимая плитка перестроена",
          tile_logical == 32, f"tile={tile_logical}")

    # пределы: значение за границами зажимается
    viewer.checker_slider.setValue(999)
    check("ползунок: максимум 32", viewer._checker_cell == CHECKER_MAX)
    viewer.checker_slider.setValue(1)
    check("ползунок: минимум 4", viewer._checker_cell == CHECKER_MIN)

    # непрозрачный JPEG — шахматка выключается
    viewer._show_index(row_jpg)
    wait_until(lambda: not viewer._view_inflight, what="JPEG прочитан")
    pump(app, 100)
    check("JPEG без альфы: шахматка выключена",
          not viewer._checker_on and viewer.view_label._tile is None)

    # текст всегда без шахматки
    viewer._set_view_checker(True)
    viewer._view_text("тест")
    check("текст: шахматка выключена",
          not viewer._checker_on and viewer.view_label._tile is None
          and viewer.view_label.text() == "тест")

    # новый экземпляр читает клетку из настроек
    settings.setValue("viewer/checker_cell", 24)
    viewer2 = LocalViewer()
    check("новый вьюер: клетка из настроек", viewer2._checker_cell == 24)
    check("новый вьюер: ползунок на 24", viewer2.checker_slider.value() == 24)
    check("новый вьюер: на старте шахматки нет",
          not viewer2._checker_on and viewer2.view_label._tile is None)

    # ---------- 9: превью выбора с клеткой из настроек ----------
    settings.setValue("viewer/checker_cell", 4)
    pm4 = _checker_pixmap(png)
    check("превью: шахматка 132×132", pm4 is not None
          and pm4.width() == 132 and pm4.height() == 132)
    img4 = pm4.toImage()
    # картинка 40×40 отмасштабирована в 28×28 и отцентрована — поля ~6px,
    # клетка 4: точка (5,1) попадает на серый квадрат
    check("превью: клетка 4 — серый квадрат в поле",
          rgb(img4, 5, 1) == QColor("#c0c0c0"), str(rgb(img4, 5, 1).name()))
    settings.setValue("viewer/checker_cell", 32)
    pm32 = _checker_pixmap(png)
    img32 = pm32.toImage()
    check("превью: клетка 32 — белый квадрат в той же точке",
          rgb(img32, 5, 1) == QColor("#ffffff"), str(rgb(img32, 5, 1).name()))

    # мусорный файл — превью нет
    junk = os.path.join(tmp, "junk.png")
    with open(junk, "wb") as f:
        f.write(b"not an image")
    check("превью: мусор — нет превью", _checker_pixmap(junk) is None)

    # настройки чтения: мусор в QSettings — дефолт
    settings.setValue("viewer/checker_cell", "мусор")
    check("настройки: мусор — дефолт", _checker_cell_setting() == CHECKER_DEFAULT)
    settings.setValue("viewer/checker_cell", 1000)
    check("настройки: 1000 зажат до 32", _checker_cell_setting() == CHECKER_MAX)

    # ---------- 10: смоук ----------
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
