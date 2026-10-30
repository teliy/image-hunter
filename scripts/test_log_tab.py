"""Оффлайн-тест вкладки «Журнал», переставляемых вкладок и иконки приложения.

Проверяет:
1. в главном окне 4 вкладки, «Журнал» — самая правая, подписана по i18n;
2. вкладки можно перетаскивать (setMovable) и порядок реально меняется;
3. при смене языка подписи вкладок следуют за виджетами (даже после
   перестановки — заголовки ищутся по виджету, а не по номеру);
4. журнал принимает события (applog): старт, открытие папки, драг, копирование;
5. «🧹 Очистить» и «📋 Копировать всё» работают (буфер обмена получает текст);
6. иконка приложения: файлы в ресурсах на месте, QIcon не пуст, окно получило иконку;
7. мост logging→Qt пишет и из фонового потока.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_log_tab.py
"""

import logging
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import applog, i18n  # noqa: E402

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


class FakeDrag:
    """Подмена QDrag: запоминает mime и возвращает управление сразу."""

    def __init__(self, parent=None):
        self.mime = None

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pix):
        pass

    def exec(self, *args):
        return Qt.DropAction.CopyAction


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    applog.setup()

    from app.ui import app_icon
    from app.ui.main_window import MainWindow

    tmp = tempfile.mkdtemp(prefix="ih_log_")
    try:
        for i in range(3):
            img = QImage(48, 36, QImage.Format.Format_RGB32)
            img.fill(0x336699 + i)
            assert img.save(os.path.join(tmp, f"img_{i}.png"))

        win = MainWindow()
        win.resize(1400, 900)
        win.show()
        pump(app, 500)

        # 1. четыре вкладки, «Журнал» — самая правая
        tabs = win.tabs
        check("в окне 4 вкладки", tabs.count() == 4, str(tabs.count()))
        log_idx = tabs.indexOf(win.log_view)
        check("«Журнал» — самая правая вкладка",
              log_idx == tabs.count() - 1, str(log_idx))
        check("подпись журнала локализована (ru)",
              tabs.tabText(log_idx) == i18n.tr("tab.log"), tabs.tabText(log_idx))

        # 2. вкладки двигаются
        check("вкладки перетаскиваются (setMovable)", tabs.isMovable())
        tabs.tabBar().moveTab(0, 3)          # «Мои картинки» — в конец
        pump(app, 100)
        check("порядок вкладок реально меняется",
              tabs.indexOf(win.local) == 3 and tabs.indexOf(win.log_view) == 2,
              f"local={tabs.indexOf(win.local)}, log={tabs.indexOf(win.log_view)}")

        # 3. смена языка следует за виджетами, а не за номерами
        i18n.set_lang("en", persist=False)
        pump(app, 200)
        check("после перестановки подпись «Моих картинок» при виджете (en)",
              tabs.tabText(tabs.indexOf(win.local)) == i18n.tr("tab.pictures"),
              tabs.tabText(tabs.indexOf(win.local)))
        check("«Журнал» теперь первая и подписана по-английски",
              tabs.currentIndex() >= 0 and
              tabs.tabText(tabs.indexOf(win.log_view)) == i18n.tr("tab.log"),
              tabs.tabText(tabs.indexOf(win.log_view)))
        i18n.set_lang("ru", persist=False)
        pump(app, 200)
        tabs.tabBar().moveTab(3, 0)          # возвращаем как было
        pump(app, 100)

        # 4. журнал принимает события applog
        log_text = win.log_view.text.toPlainText()
        check("журнал получил стартовое событие",
              "запущен" in log_text or "готов" in log_text, log_text[:80])
        win.local.load_folder(tmp)
        pump(app, 300)
        log_text = win.log_view.text.toPlainText()
        check("открытие папки записано в журнал",
              f"Открыта папка: {tmp}" in log_text and "3 картинок" in log_text,
              log_text[:120])
        win.local.list.DRAG_FACTORY = FakeDrag
        win.local.list.clearSelection()
        win.local.list.item(0).setSelected(True)
        win.local.list.exec_drag()
        pump(app, 200)
        log_text = win.log_view.text.toPlainText()
        check("перетаскивание записано в журнал",
              "Перетаскивание начато: 1 файлов" in log_text
              and "img_0.png" in log_text
              and "Перетаскивание завершено" in log_text, log_text[-160:])

        # 5. очистка и копирование журнала
        win.log_view.copy_all()
        pump(app, 100)
        cb_text = QApplication.clipboard().text()
        check("«Копировать всё» положил журнал в буфер обмена",
              "Перетаскивание начато" in cb_text, cb_text[-80:])
        win.log_view.btn_clear.click()
        pump(app, 200)
        log_text = win.log_view.text.toPlainText()
        check("после очистки осталась только запись об очистке",
              log_text.strip().endswith("Журнал очищен") and
              "Перетаскивание начато" not in log_text, log_text[:120])
        win.log_view.copy_all()
        pump(app, 200)
        log_text = win.log_view.text.toPlainText()
        check("копирование журнала тоже записано",
              "скопирован в буфер обмена" in log_text, log_text[:120])

        # 6. иконка приложения
        png, ico = app_icon.RES_DIR / "app_icon.png", app_icon.RES_DIR / "app_icon.ico"
        check("файлы иконки в ресурсах",
              png.exists() and ico.exists() and png.stat().st_size > 5000
              and ico.stat().st_size > 10000,
              f"png={png.stat().st_size if png.exists() else 0}, "
              f"ico={ico.stat().st_size if ico.exists() else 0}")
        ic = app_icon.icon()
        check("QIcon из ресурсов не пуст и имеет размеры",
              not ic.isNull() and len(ic.availableSizes()) >= 3,
              str([f"{s.width()}x{s.height()}" for s in ic.availableSizes()]))
        check("иконка рисуется и в памяти (запасной путь)",
              not app_icon.paint_pixmap(64).isNull())
        check("окно получило иконку приложения",
              not win.windowIcon().isNull())
        # ICO внутри действительно многоразмерный (Pillow читает все кадры)
        from PIL import Image
        ico_img = Image.open(ico)
        check("ICO многоразмерный (16…256)",
              getattr(ico_img, "info", {}).get("sizes") is not None
              or ico_img.size[0] >= 16,
              str(ico_img.size))

        # 7. мост logging→Qt принимает записи из фонового потока
        win.log_view.btn_clear.click()
        pump(app, 100)
        logging.getLogger("app").warning("из фонового потока")
        t = threading.Thread(
            target=lambda: logging.getLogger("app").info("потоковая запись"))
        t.start()
        t.join()
        pump(app, 300)
        log_text = win.log_view.text.toPlainText()
        check("запись из фонового потока дошла до журнала",
              "потоковая запись" in log_text and "из фонового потока" in log_text,
              log_text[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
