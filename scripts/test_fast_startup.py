"""Оффлайн-тест «быстрый старт и ленивый браузер» (v0.7.0).

Проверяется модульность v0.7.0 и её главный эффект — программа не
запускает ни одного процесса Chromium, пока пользователь не открыл
вкладку поиска:

1. app/core/engines.py — данные поисковиков живут отдельным модулем,
   app/ui/web_search.py только реэкспортирует ENGINES/is_image_search_url;
2. app/core/webengine.py — вся настройка WebEngine в одном месте:
   детект поломанного Wayland, apply_gpu_fix (IH_GPU), базовые флаги
   Linux (--disable-dev-shm-usage), песочница (IH_NO_SANDBOX,
   автодетект запрещённых user-namespace), watchdog загрузки;
3. ленивый WebSearch: свежая вкладка без браузера; поиск фоновой
   вкладки запоминается (pending) и выполняется при показе; повторный
   _ensure_view() не создаёт второй браузер; current_url() без браузера —
   пустой QUrl;
4. SearchTabs: восстановление любого числа вкладок не создаёт ни одного
   браузера; «Найти везде» при скрытой панели откладывает выдачу всех
   вкладок (нет шторма загрузок); дублирование скрытой вкладки работает;
5. главное окно после старта не содержит ни одного QWebEngineView.

Запуск: QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" python scripts/test_fast_startup.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def _env_backup() -> dict:
    return {k: os.environ.get(k, "") for k in
            ("IH_GPU", "IH_NO_SANDBOX", "QTWEBENGINE_CHROMIUM_FLAGS")}


def _env_restore(bak: dict) -> None:
    for k, v in bak.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ---------- 1. модуль движков ----------

def test_engines_module() -> None:
    from app.core import engines
    from app.ui import web_search

    check("ENGINES реэкспортируется без копии",
          web_search.ENGINES is engines.ENGINES)
    check("поисковиков 11", len(engines.ENGINES) == 11, str(len(engines.ENGINES)))
    check("Yahoo удалён", not any("yahoo" in e[1].lower() for e in engines.ENGINES))
    check("Ecosia удалён", not any("ecosia" in e[1].lower() for e in engines.ENGINES))
    check("is_image_search_url: выдача Яндекса",
          engines.is_image_search_url("https://ya.ru/images/search?text=cats"))
    check("is_image_search_url: выдача Bing",
          engines.is_image_search_url("https://www.bing.com/images/search?q=cats"))
    check("is_image_search_url: чужой сайт — нет",
          not engines.is_image_search_url("https://example.com/gallery"))
    check("у каждого движка 4 поля метаданных",
          all(len(e) == 4 for e in engines.ENGINES))


# ---------- 2. модуль webengine ----------

def test_webengine_module() -> None:
    from app.core import webengine

    WAYLAND_MSG = ('qt.qpa.plugin: Could not load the Qt platform plugin "wayland" '
                   'in "" even though it was found.')
    check("детект строки из отчёта пользователя",
          webengine.wayland_fallback_failed([WAYLAND_MSG]))
    check("чужой варнинг — не повод",
          not webengine.wayland_fallback_failed(["xcb failed"]))

    bak = _env_backup()
    try:
        os.environ["IH_GPU"] = "0"
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        check("IH_GPU=0: GPU выключен принудительно", webengine.apply_gpu_fix() is True)
        check("IH_GPU=0: --disable-gpu в флагах",
              "--disable-gpu" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))
        os.environ.pop("IH_GPU", None)

        if sys.platform == "linux":
            base = webengine._linux_base_flags()
            check("Linux: --disable-dev-shm-usage всегда",
                  "--disable-dev-shm-usage" in base, str(base))
            os.environ["IH_NO_SANDBOX"] = "1"
            check("IH_NO_SANDBOX=1: песочница отключается по просьбе",
                  "--no-sandbox" in webengine._linux_base_flags())
            os.environ["IH_NO_SANDBOX"] = "0"
            check("IH_NO_SANDBOX=0: песочница не отключается",
                  "--no-sandbox" not in webengine._linux_base_flags())
            os.environ.pop("IH_NO_SANDBOX", None)

        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        os.environ.pop("IH_NO_SANDBOX", None)
        fixes = webengine.apply_env_fixes()
        check("apply_env_fixes возвращает решения",
              isinstance(fixes, dict) and "gpu_off" in fixes and "sandbox_off" in fixes,
              str(fixes))
    finally:
        _env_restore(bak)


def test_watchdog() -> None:
    from PySide6.QtCore import QObject, QTimer, Signal

    from app.core import applog, webengine

    class _StubUrl:
        def toString(self) -> str:
            return "https://ya.ru/images/search?text=cats"

    class _StubView(QObject):
        loadStarted = Signal()
        loadFinished = Signal(bool)

        def __init__(self):
            super().__init__()
            self.stopped = False

        def url(self):
            return _StubUrl()

        def stop(self):
            self.stopped = True

    view = _StubView()
    timer = webengine.attach_load_watchdog(view)
    check("watchdog: таймер-одноразка", timer.isSingleShot())
    check("watchdog: интервал 45 с", timer.interval() == webengine.LOAD_TIMEOUT_MS)
    check("watchdog: таймер принадлежит view", timer.parent() is view)
    check("watchdog: имя для поиска в тестах", timer.objectName() == "ih-load-watchdog")

    events: list[tuple] = []
    real_event = applog.event
    applog.event = lambda key, **kw: events.append((key, kw))   # type: ignore[assignment]
    try:
        webengine._watchdog_fire(view)
    finally:
        applog.event = real_event   # type: ignore[assignment]
    check("watchdog: загрузка остановлена", view.stopped)
    check("watchdog: событие в журнале",
          bool(events) and events[0][0] == "log.event.load_watchdog", str(events))
    check("watchdog: в событии есть url и секунды",
          bool(events) and "url" in events[0][1] and "sec" in events[0][1])


# ---------- 3–4. ленивый WebSearch и SearchTabs ----------

def test_lazy_search() -> None:
    from PySide6.QtCore import QSettings, QUrl
    from PySide6.QtWidgets import QApplication

    from app.core import i18n
    from app.core.engines import ENGINES
    from app.ui.web_search import WebSearch

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("ImageHunter")
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("web/tabs", "")

    ws = WebSearch()
    check("свежая вкладка без браузера", ws._view is None)
    check("свежая вкладка без отложенного поиска", ws._pending_url == "")
    check("current_url без браузера — пустой QUrl", ws.current_url().isEmpty())

    # фоновая вкладка: поиск запоминается, Chromium не запускается
    ddg = ENGINES[1][1]
    ws.engine.setCurrentIndex(1)
    ws.query.setText("котики")
    ws.search()
    check("скрытая вкладка: браузер не создан", ws._view is None)
    check("скрытая вкладка: поиск отложен",
          ws._pending_url == ddg.format("котики") or "duckduckgo" in ws._pending_url,
          ws._pending_url)
    check("скрытая вкладка: current_url всё ещё пуст", ws.current_url().isEmpty())

    # показ вкладки: браузер создаётся, отложенный поиск выполняется
    ws.resize(800, 600)
    ws.show()
    app.processEvents()
    check("показ вкладки: браузер создан", ws._view is not None)
    check("показ вкладки: отложенный поиск израсходован", ws._pending_url == "")
    check("показ вкладки: view стабильна (property не создаёт вторую)",
          ws.view is ws._view)

    # видимой вкладке адрес открывается сразу
    ws.open_url("https://example.com/gallery")
    check("видимая вкладка: адрес открыт сразу", ws._pending_url == "")
    # у вкладки с УЖЕ созданным браузером скрытие ничего не откладывает:
    # рендер-процесс жив, загрузка дешёвая — отложка нужна только ДО запуска Chromium
    ws.hide()
    ws.open_url("https://ya.ru/images/")
    check("скрытая вкладка с браузером: адрес открывается сразу",
          ws._pending_url == "" and ws._view is not None)
    ws.deleteLater()


def test_search_tabs_lazy() -> None:
    from urllib.parse import unquote

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from app.core import i18n
    from app.core.engines import ENGINES
    from app.ui.search_tabs import SETTINGS_KEY, _SEP, SearchTabs

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("ImageHunter")
    i18n.set_lang("ru", persist=False)

    # «прошлая сессия»: в настройках сохранены все 11 поисковиков
    names = _SEP.join(name for name, _tpl, _short, _color in ENGINES)
    QSettings("ImageHunter", "ImageHunter").setValue(SETTINGS_KEY, names)

    panel = SearchTabs()   # восстанавливает сохранённые вкладки
    # восстановление «прошлой сессии»: сколько бы вкладок ни было — ноль Chromium
    # (дополнительно по одной: две вкладки одного поисковика)
    for name, _tpl, _short, _color in ENGINES[:2]:
        panel.add_tab(engine_name=name, focus=False, quiet=True)
    check("вкладки восстановлены (11 + 2 дубликата)",
          panel.tabs.count() == len(ENGINES) + 2, str(panel.tabs.count()))
    check("ни одна вкладка не запустила Chromium",
          all(panel.tabs.widget(i)._view is None for i in range(panel.tabs.count())))

    # «Найти везде» на скрытой панели: все вкладки лишь запоминают выдачу
    panel.global_query.setText("закат")
    panel.search_everywhere()
    hidden_pending = [panel.tabs.widget(i)._pending_url
                      for i in range(panel.tabs.count())]
    check("поиск везде: ни один браузер не запущен",
          all(panel.tabs.widget(i)._view is None for i in range(panel.tabs.count())))
    check("поиск везде: у каждой вкладки свой отложенный адрес",
          all(p for p in hidden_pending), str(hidden_pending[:3]))
    check("поиск везде: Яндекс ищет «закат»",
          any("ya.ru/images/search" in p and "закат" in unquote(p)
              for p in hidden_pending))
    check("поиск везде: запрос во всех строках вкладок",
          all(panel.tabs.widget(i).query.text() == "закат"
              for i in range(panel.tabs.count())))

    # дублирование скрытой вкладки не требует браузера у источника
    idx = 2
    panel._duplicate_tab(idx)
    check("дубликат создан", panel.tabs.count() == len(ENGINES) + 3)
    dup = panel.tabs.currentWidget()
    check("дубликат: у источника по-прежнему нет браузера",
          panel.tabs.widget(idx)._view is None)
    check("дубликат: запрос скопирован и отложен",
          dup.query.text() == "закат" and dup._pending_url != "")

    panel.deleteLater()
    app.processEvents()


# ---------- 5. главное окно: после старта Chromium нет ----------

def test_main_window_no_chromium() -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from app.core import i18n

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("ImageHunter")
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("web/tabs", "")

    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.ui.main_window import MainWindow

    win = MainWindow()
    check("главное окно: ни одного QWebEngineView после старта",
          win.findChildren(QWebEngineView) == [])
    check("главное окно: стартует на «Моих картинках»",
          win.tabs.currentWidget() is win.local)
    win.deleteLater()
    app.processEvents()


def main() -> int:
    test_engines_module()
    test_webengine_module()
    test_watchdog()
    test_lazy_search()
    test_search_tabs_lazy()
    test_main_window_no_chromium()
    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}: " + "; ".join(FAILURES))
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
