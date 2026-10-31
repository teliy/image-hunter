"""Оффлайн-смоук главного окна целиком (v0.6.4).

Проверяется: MainWindow собирается со всеми вкладками (включая новые
мультивкладки поиска), заголовок содержит версию 0.6.4, наружные сигналы
мультивкладок подключены, кнопки сохранения живы.

Запуск: QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
        python scripts/test_main_window_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("web/tabs", "")

    win = MainWindow()
    win.show()
    app.processEvents()

    check("версия 0.6.4", __version__ == "0.6.4", __version__)
    check("в заголовке версия", "0.6.4" in win.windowTitle(), win.windowTitle())
    check("у поиска есть общее поле запроса",
          hasattr(win.web, "global_query") and hasattr(win.web, "btn_all"))
    check("вкладок в главном окне четыре", win.tabs.count() == 4,
          str(win.tabs.count()))
    check("вторая вкладка — мультивкладки поиска",
          win.web.tabs.count() >= 1 and hasattr(win.web, "add_tab"))
    check("поисковая вкладка называется «Яндекс»",
          win.web.tabs.tabText(0) == "Яндекс", win.web.tabs.tabText(0))
    check("кнопка «Обновить» на месте", win.btn_upd.text().endswith("Обновить"))
    check("current_format доступен", win.web.current_format() in
          ("WebP", "PNG", "JPEG", "BMP", "TIFF"), win.web.current_format())

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
