"""Оффлайн-тест общего поля запроса «поиск во всех поисковиках» (v0.6.0).

Проверяется:
1. над вкладками есть общее поле запроса и кнопка «Найти везде»;
2. пустой запрос — фокус в поле, поиск не запускается, вкладок не прибавляется;
3. запрос в поле: для каждого поисковика открывается своя вкладка
   (уже открытые переиспользуются) и в каждой запускается поиск;
4. повторный запрос вкладок не плодит, но поиск запускает заново;
5. набор открытых поисковиков сохраняется в настройки (восстановится при старте);
6. событие поиска пишется в журнал;
7. перетрансляция при смене языка не падает.

WebSearch подменяется лёгким фейком (без Chromium): проверяется логика
раскладки запроса по вкладкам, а не загрузка страниц (её покрывают
смок-тест и ручная проверка).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_search_everywhere.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.core import applog, i18n  # noqa: E402
from app.core.i18n import tr  # noqa: E402
from app.ui import search_tabs as st  # noqa: E402
from app.ui.search_tabs import SearchTabs  # noqa: E402
from app.ui.web_search import ENGINES  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


class _FakeCombo(QObject):
    """Комбо поисковика:setCurrentIndex/currentIndex + сигнал смены."""

    currentTextChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self._idx = 0

    def setCurrentIndex(self, i: int) -> None:
        self._idx = i

    def currentIndex(self) -> int:
        return self._idx


class _FakeLine:
    """QLineEdit-заглушка: только setText/text."""

    def __init__(self):
        self._t = ""

    def setText(self, t: str) -> None:
        self._t = t

    def text(self) -> str:
        return self._t


class FakeWebSearch(QWidget):
    """Лёгкая замена WebSearch: те же сигналы и счётчики поисков."""

    images_found = Signal(list, str)
    checked_count_changed = Signal(int)
    save_requested = Signal(list, str)

    searches: list[tuple[str, str]] = []   # [(поисковик, запрос), …] всех фейков
    instances: list["FakeWebSearch"] = []

    def __init__(self):
        super().__init__()
        self.engine = _FakeCombo()
        self.query = _FakeLine()
        self.search_calls = 0
        FakeWebSearch.instances.append(self)

    def engine_meta(self) -> tuple[str, str, str, str]:
        return ENGINES[self.engine.currentIndex()]

    def search(self) -> None:
        self.search_calls += 1
        FakeWebSearch.searches.append((self.engine_meta()[0], self.query.text()))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    applog.setup()
    QSettings("ImageHunter", "ImageHunter").setValue(st.SETTINGS_KEY, "")

    st.WebSearch = FakeWebSearch   # без Chromium — только логика раскладки

    c = SearchTabs()
    check("при старте одна вкладка", c.tabs.count() == 1, str(c.tabs.count()))

    # 1. общее поле на месте и локализовано
    check("общее поле запроса создано", hasattr(c, "global_query"))
    check("кнопка «Найти везде» создана", hasattr(c, "btn_all"))
    check("плейсхолдер общего поля",
          c.global_query.placeholderText() == tr("ws.all_query_ph"),
          c.global_query.placeholderText())
    check("подпись кнопки", c.btn_all.text() == tr("ws.all_find"), c.btn_all.text())
    check("подсказка кнопки называет число поисковиков",
          tr("ws.all_find_tip", n=len(ENGINES)) in c.btn_all.toolTip(),
          c.btn_all.toolTip())

    # 2. пустой запрос — ничего не делаем
    FakeWebSearch.searches.clear()
    c.global_query.setText("   ")
    c.search_everywhere()
    check("пустой запрос не ищет", not FakeWebSearch.searches)
    check("пустой запрос не открывает вкладок", c.tabs.count() == 1,
          str(c.tabs.count()))

    # 3. запрос → вкладка на каждый поисковик
    c.global_query.setText("23542-23523")
    c.search_everywhere()
    check("вкладка на каждый поисковик", c.tabs.count() == len(ENGINES),
          f"{c.tabs.count()} != {len(ENGINES)}")
    engines_in_tabs = [c.tabs.widget(i).engine_meta()[0] for i in range(c.tabs.count())]
    check("открыты все поисковики и без повторов",
          set(engines_in_tabs) == {e[0] for e in ENGINES}
          and len(engines_in_tabs) == len(ENGINES), str(engines_in_tabs))
    check("поиск запущен в каждой вкладке",
          all(w.search_calls == 1 for w in FakeWebSearch.instances),
          str([w.search_calls for w in FakeWebSearch.instances]))
    check("запрос подставлен каждой вкладке",
          all(w.query.text() == "23542-23523" for w in FakeWebSearch.instances))
    check("записей поиска — по числу вкладок",
          len(FakeWebSearch.searches) == len(ENGINES), str(len(FakeWebSearch.searches)))

    # 4. повторный запрос: вкладки переиспользуются, поиск перезапускается
    before = c.tabs.count()
    c.global_query.setText("toyota corolla")
    c.search_everywhere()
    check("повторный запрос не плодит вкладок", c.tabs.count() == before,
          f"{c.tabs.count()} != {before}")
    check("поиск перезапущен во всех вкладках",
          all(w.search_calls == 2 for w in FakeWebSearch.instances),
          str([w.search_calls for w in FakeWebSearch.instances]))

    # 5. набор поисковиков сохранён в настройках (порядок = ENGINES)
    saved = QSettings("ImageHunter", "ImageHunter").value(st.SETTINGS_KEY, "", str)
    check("в настройках все поисковики по порядку",
          str(saved).split("|") == [e[0] for e in ENGINES], str(saved))

    # 6. событие поиска — в журнал
    events: list[tuple] = []
    orig_event = st.applog.event
    st.applog.event = lambda key, **kw: events.append((key, kw))
    c.global_query.setText("бампер")
    c.search_everywhere()
    st.applog.event = orig_event
    check("событие журнала search_all записано",
          any(k == "log.event.search_all" and kw.get("n") == len(ENGINES)
              for k, kw in events), str(events))

    # 7. перетрансляция при смене языка
    i18n.set_lang("en", persist=False)
    check("плейсхолдер переведён (en)",
          c.global_query.placeholderText() == tr("ws.all_query_ph"),
          c.global_query.placeholderText())
    check("кнопка переведена (en)", c.btn_all.text() == tr("ws.all_find"),
          c.btn_all.text())
    i18n.set_lang("ru", persist=False)
    check("и обратно на русский", c.btn_all.text() == tr("ws.all_find"),
          c.btn_all.text())

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
