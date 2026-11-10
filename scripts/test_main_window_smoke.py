"""Оффлайн-смоук главного окна целиком (v0.8.2).

Проверяется: MainWindow собирается со всеми вкладками (включая новые
мультивкладки поиска), заголовок содержит версию 0.8.10, наружные сигналы
мультивкладок подключены (теперь с именем поисковика), кнопки сохранения
живы, статус «Моих картинок» — в строке статуса внизу окна, меню «Модули»
на месте слева от «Справки».

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

    check("версия 0.8.10", __version__ == "0.8.10", __version__)
    check("в заголовке версия", "0.8.10" in win.windowTitle(), win.windowTitle())
    # сигналы поиска несут имя поисковика (v0.7.8): emit с 3 аргументами
    # через релей SearchTabs доходит до приёмника MainWindow
    got_engines: list[str] = []
    win.web.images_found.connect(lambda urls, ref, eng: got_engines.append(eng))
    inner_ws = win.web.tabs.widget(0)
    inner_ws.images_found.emit(["http://x/1.jpg"], "http://referer",
                               inner_ws.engine_meta()[2])
    app.processEvents()
    check("сигналы поиска несут имя поисковика",
          got_engines == [inner_ws.engine_meta()[2]], str(got_engines))
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

    # статус «Моих картинок» переехал в строку статуса (v0.7.7)
    st = win.local.status
    check("статус вьюера — ребёнок статус-бара", st.parent() is win._status,
          str(st.parent()))
    check("статус вьюера слева от языка",
          st.geometry().x() < win.lang_box.geometry().x(),
          f"{st.geometry().x()} vs {win.lang_box.geometry().x()}")
    check("язык левее кнопки обновления",
          win.lang_box.geometry().x() < win.btn_upd.geometry().x(),
          f"{win.lang_box.geometry().x()} vs {win.btn_upd.geometry().x()}")
    check("текст статуса вьюера виден", bool(st.text()), st.text())

    # меню «Модули» (v0.8.2): слева от «Справки», модуль сервера ленивый
    top = win.menuBar().actions()
    check("меню «Модули» в строке меню",
          len(top) >= 2 and top[-2].text() == i18n.tr("menu.modules"),
          str([a.text() for a in top]))
    check("«Справка» правее «Модулей»",
          top[-1].text() == i18n.tr("menu.help"), top[-1].text())
    check("кнопки веб-сервера в статус-баре больше нет",
          not hasattr(win, "btn_server"))
    check("менеджер сервера ленивый (не создан)",
          getattr(win, "_server_mgr", "no-attr") is None)
    check("список импортированных модулей без app.server",
          not any(m == "app.server" or m.startswith("app.server.")
                  for m in list(sys.modules)))

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
