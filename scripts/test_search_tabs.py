"""Оффлайн-тест мультивкладок поиска «как в браузере» (v0.4.0).

Проверяется:
1. при старте есть хотя бы одна вкладка, заголовок — короткое имя поисковика,
   значок — фирменный цвет бренда;
2. «＋»/add_tab добавляет вкладку с поисковиком текущей вкладки;
3. смена поисковика в комбо переименовывает вкладку и меняет цвет;
4. дублирование: тот же поисковик и тот же запрос;
5. закрытие вкладки, закрытие последней (заменяется свежей), закрыть
   другие/справа;
6. открытые поисковики запоминаются и восстанавливаются в новом контейнере;
7. лимит вкладок (MAX_TABS) соблюдается;
8. сигналы внутренней вкладки пересылаются наружу.

Запуск: QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
        python scripts/test_search_tabs.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import applog, i18n  # noqa: E402
from app.ui import search_tabs as st  # noqa: E402
from app.ui.search_tabs import SearchTabs  # noqa: E402
from app.ui.web_search import ENGINES  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def tab_titles(container: SearchTabs) -> list[str]:
    return [container.tabs.tabText(i) for i in range(container.tabs.count())]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    applog.setup()
    QSettings("ImageHunter", "ImageHunter").setValue(st.SETTINGS_KEY, "")

    # 1. старт: одна вкладка, заголовок — короткое имя поисковика
    c = SearchTabs()
    check("при старте одна вкладка", c.tabs.count() == 1, str(c.tabs.count()))
    check("заголовок = короткое имя поисковика",
          c.tabs.tabText(0) == ENGINES[0][2], c.tabs.tabText(0))
    check("у вкладки есть значок-кружок", not c.tabs.tabIcon(0).isNull())
    check("подсказка вкладки — полное имя поисковика",
          c.tabs.tabToolTip(0) == ENGINES[0][0], c.tabs.tabToolTip(0))
    check("крестик на вкладках", c.tabs.tabsClosable())
    check("вкладки перетаскиваются", c.tabs.isMovable())
    check("кнопка «＋» в углу", c.tabs.cornerWidget() is not None)

    # 2. новая вкладка: поисковик берётся у текущей
    ws2 = c.add_tab()
    check("вторая вкладка добавлена", c.tabs.count() == 2)
    check("новая вкладка — с поисковиком текущей",
          ws2.engine_meta()[0] == ENGINES[0][0], ws2.engine_meta()[0])

    # 3. смена поисковика → заголовок и цвет вкладки
    ws2.engine.setCurrentIndex(2)   # Google
    app.processEvents()
    idx = c.tabs.indexOf(ws2)
    check("вкладка переименовалась в Google",
          c.tabs.tabText(idx) == "Google", c.tabs.tabText(idx))
    check("цвет вкладки — фирменный Google (#4285F4)",
          c.tabs.tabIcon(idx).pixmap(16, 16).toImage().pixelColor(8, 8).name()
          == "#4285f4")

    # 4. дублирование: тот же поисковик и запрос
    ws2.query.setText("31112-1R100")
    c._duplicate_tab(idx)
    check("после дублирования вкладок три", c.tabs.count() == 3)
    dup = c.tabs.widget(c.tabs.count() - 1)
    check("дубль — тот же поисковик",
          dup.engine_meta()[0] == "Google Картинки", dup.engine_meta()[0])
    check("дубль — тот же запрос",
          dup.query.text() == "31112-1R100", dup.query.text())

    # 5. закрытие: крестик по индексу
    c._close_tab(c.tabs.count() - 1)     # закрыли дубль
    check("дубль закрылся", c.tabs.count() == 2)
    c._close_tab(0)                      # закрываем последнюю вкладку Яндекс
    check("последнюю тоже можно закрыть — остаётся вторая",
          c.tabs.count() == 1, str(c.tabs.count()))

    # 6. «закрыть другие» и «закрыть справа»
    c.add_tab(); c.add_tab(); c.add_tab()
    total = c.tabs.count()
    c._close_others(1)
    check("«закрыть другие» оставила одну", c.tabs.count() == 1,
          str(tab_titles(c)))
    c.add_tab(); c.add_tab()
    c._close_right(0)
    check("«закрыть справа» оставила первую", c.tabs.count() == 1)

    # 7. закрытие последней заменяется свежей — поиск без вкладки не остаётся
    c._close_tab(0)
    check("после закрытия единственной вкладки появилась свежая",
          c.tabs.count() == 1, str(c.tabs.count()))

    # 8. запоминание и восстановление набора поисковиков
    c.tabs.widget(0).engine.setCurrentIndex(1)   # DuckDuckGo
    app.processEvents()
    c.add_tab(engine_name="Bing Картинки")
    saved = QSettings("ImageHunter", "ImageHunter").value(st.SETTINGS_KEY, "", str)
    check("настройки сохранили поисковики",
          saved == "DuckDuckGo (safe)|Bing Картинки", str(saved))
    c2 = SearchTabs()
    check("новый контейнер восстановил вкладки", c2.tabs.count() == 2,
          str(tab_titles(c2)))
    check("восстановлен DuckDuckGo",
          c2.tabs.tabText(0) == "DuckDuckGo", c2.tabs.tabText(0))
    check("восстановлен Bing",
          c2.tabs.tabText(1) == "Bing", c2.tabs.tabText(1))

    # 9. лимит вкладок
    st.MAX_TABS = 3
    try:
        c2.add_tab()
        check("третья вкладка открылась", c2.tabs.count() == 3)
        extra = c2.add_tab()
        check("четвёртая отклонена (лимит)", extra is None)
    finally:
        st.MAX_TABS = 16

    # 10. сигналы внутренней вкладки пересылаются наружу
    got: list[str] = []
    c2.save_requested.connect(lambda urls, ref: got.append(ref))
    inner = c2.tabs.widget(0)
    inner.save_requested.emit(["http://x/1.jpg"], "http://referer")
    app.processEvents()
    check("save_requested доходит наружу", got == ["http://referer"], str(got))

    # 11. наружный интерфейс совместим со старым кодом MainWindow
    check("current_format() отдаёт формат активной вкладки",
          c2.current_format() in ("WebP", "PNG", "JPEG", "BMP", "TIFF"),
          c2.current_format())
    c2.tabs.setCurrentIndex(0)     # сделать первую вкладку (DuckDuckGo) активной
    app.processEvents()
    inner.query.setText("тест-запрос")
    check("current_query() читает запрос активной вкладки",
          c2.current_query() == "тест-запрос", c2.current_query())

    # 12. имена/цвета поисковиков: у каждого короткое имя и цвет-HEX
    for name, _u, short, color in ENGINES:
        check(f"у «{name}» есть короткое имя и цвет",
              bool(short) and color.startswith("#") and len(color) == 7,
              f"{short}/{color}")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
