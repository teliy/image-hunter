"""Оффлайн-тест защиты от зависаний QtWebEngine на Linux (v0.6.4).

Проверяется:
1. wayland_fallback_failed(): распознаёт ровно ту строку из пользовательских
   отчётов (``Could not load the Qt platform plugin "wayland" … even though
   it was found``) и вариант «Could not find»; чужие предупреждения (xcb,
   обычные варнинги) и пустой список — не сигнал;
2. _apply_webengine_gpu_fix(): IH_GPU=1 — GPU остаётся; IH_GPU=0 —
   --disable-gpu принудительно; чужие флаги QTWEBENGINE_CHROMIUM_FLAGS
   дополняются, а не затираются; без предупреждений и override — ничего
   не меняется; при предупреждении wayland — --disable-gpu добавляется
   сам и только один раз;
3. инъекция чекбоксов null-safe: appendChild больше не выполняется по
   «голому» document.head||documentElement, всё завёрнуто в try/catch;
4. гейт опроса чекбоксов: на странице-не-выдаче дерево фреймов не
   обходится и счётчик обнуляется без похода в браузер; на выдаче
   запрос __IH_CB_COUNT уходит в главный фрейм;
5. _on_render_gone: падение процесса отрисовки перезапускает вкладку,
   но не больше двух раз; журнал получает событие;
6. Mail.ru-обёртка (go.mail.ru/search_images) считается выдачей — иначе
   гейт опроса сломал бы вложенные фреймы.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_gpu_fix.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


# ---------- части 1–2: чистый Python, Qt не нужен ----------

import main as entry  # noqa: E402  # корневой main.py приложения

WAYLAND_MSG = ('qt.qpa.plugin: Could not load the Qt platform plugin "wayland" in "" '
               'even though it was found.')
WAYLAND_MISSING = 'qt.qpa.plugin: Could not find the Qt platform plugin "wayland"'
XCB_MSG = 'qt.qpa.plugin: Could not load the Qt platform plugin "xcb"'
OTHER_MSG = 'Qt warning about something else entirely'


def test_detector() -> None:
    check("детектор: строка из отчёта пользователя",
          entry.wayland_fallback_failed([WAYLAND_MSG]))
    check("детектор: плагин не найден (Alpine без qt-wayland)",
          entry.wayland_fallback_failed([WAYLAND_MISSING]))
    check("детектор: падение xcb — не повод",
          not entry.wayland_fallback_failed([XCB_MSG]))
    check("детектор: посторонний варнинг — не повод",
          not entry.wayland_fallback_failed([OTHER_MSG]))
    check("детектор: пусто — не повод", not entry.wayland_fallback_failed([]))
    check("детектор: wayland без слов о плагине — не повод",
          not entry.wayland_fallback_failed(["wayland is great"]))
    check("детектор: смесь — находит wayland среди других",
          entry.wayland_fallback_failed([OTHER_MSG, WAYLAND_MSG, XCB_MSG]))


def _env_backup() -> dict:
    return {k: os.environ.get(k, "") for k in ("IH_GPU", "QTWEBENGINE_CHROMIUM_FLAGS")}


def _env_restore(bak: dict) -> None:
    for k, v in bak.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_gpu_fix() -> None:
    bak = _env_backup()
    try:
        # IH_GPU=1 — автодетект игнорируется, GPU остаётся
        os.environ["IH_GPU"] = "1"
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        entry._qpa_warnings.clear()
        entry._qpa_warnings.append(WAYLAND_MSG)
        check("IH_GPU=1: фикс не применяется", entry._apply_webengine_gpu_fix() is False)
        check("IH_GPU=1: флаги не тронуты",
              "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ)

        # IH_GPU=0 — принудительно, даже без предупреждений
        os.environ["IH_GPU"] = "0"
        entry._qpa_warnings.clear()
        check("IH_GPU=0: фикс применён", entry._apply_webengine_gpu_fix() is True)
        check("IH_GPU=0: --disable-gpu выставлен",
              os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") == "--disable-gpu",
              os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))

        # чужие флаги дополняются
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--force-color-profile=srgb"
        entry._apply_webengine_gpu_fix()
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        check("чужие флаги сохранены", "--force-color-profile=srgb" in flags, flags)
        check("--disable-gpu дописан", "--disable-gpu" in flags, flags)

        # повторный вызов не дублирует флаг
        entry._apply_webengine_gpu_fix()
        flags2 = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        check("повтор не дублирует флаг", flags2.count("--disable-gpu") == 1, flags2)

        # автодетект: предупреждение wayland — фикс, xcb — нет
        os.environ.pop("IH_GPU", None)
        entry._qpa_warnings[:] = [WAYLAND_MSG]
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        check("автодетект wayland: фикс применён",
              entry._apply_webengine_gpu_fix() is True
              and "--disable-gpu" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""))
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        entry._qpa_warnings[:] = [XCB_MSG]
        check("автодетект xcb: ничего не делает",
              entry._apply_webengine_gpu_fix() is False
              and "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ)
    finally:
        _env_restore(bak)
        entry._qpa_warnings.clear()


# ---------- части 3–6: живые Qt-объекты ----------

def test_qt_parts() -> None:
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineCore import QWebEnginePage

    from app.core import i18n
    from app.core.extractor import CHECKBOX_INIT_JS
    from app.ui.web_search import WebSearch, is_image_search_url

    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("ImageHunter")
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("web/tabs", "")

    # 3. null-safe инъекция стилей
    check("инъекция: root сохранён в переменную с проверкой",
          "const root = document.head || document.documentElement;" in CHECKBOX_INIT_JS
          and "if (!root) return;" in CHECKBOX_INIT_JS)
    check("инъекция: голого appendChild больше нет",
          "(document.head || document.documentElement).appendChild" not in CHECKBOX_INIT_JS)
    check("инъекция: injectStyle под try/catch",
          "const injectStyle = () => {\n    try {" in CHECKBOX_INIT_JS
          and "try { injectStyle(); scan(); } catch (e) {}" in CHECKBOX_INIT_JS)

    # 6. Mail.ru-обёртка — выдача (гейт опроса не должен её отсекать)
    check("go.mail.ru/search_images — выдача",
          is_image_search_url("https://go.mail.ru/search_images?q=cats"))
    check("ya.ru/images/ — выдача",
          is_image_search_url("https://ya.ru/images/"))

    ws = WebSearch()

    # подменяем view стабом: url + reload; page — с главным фреймом-стабом
    calls: list[str] = []

    class _StubPage:
        def mainFrame(self):
            return self

        def children(self):
            return []

        def isValid(self):
            return False

        def runJavaScript(self, code, cb=None):
            calls.append(code)
            if cb:
                cb(0)

    class _StubUrl:
        def __init__(self, s: str):
            self._s = s

        def toString(self) -> str:
            return self._s

        def isEmpty(self) -> bool:
            return not self._s

    class _StubView:
        def __init__(self, url: str):
            self._url = _StubUrl(url)
            self.page = lambda: _StubPage()
            self.reload = lambda: calls.append("reload")

        def url(self):
            return self._url

    # 4. гейт опроса: не-выдача → без обхода фреймов, счётчик в 0
    ws.isVisible = lambda: True          # type: ignore[method-assign]
    ws.view = _StubView("https://example.com/gallery")   # type: ignore[assignment]
    ws._on_poll_result(3)                # сделаем счётчик ненулевым
    calls.clear()
    ws._poll_checked_count()
    check("гейт: не-выдача — JS не выполнялся", not calls, str(calls))
    check("гейт: счётчик обнулён, кнопки погашены",
          ws._checked_count == 0 and not ws.btn_checked.isEnabled())

    # выдача → запрос __IH_CB_COUNT к главному фрейму
    ws.view = _StubView("https://ya.ru/images/search?text=cats")   # type: ignore[assignment]
    calls.clear()
    ws._poll_checked_count()
    check("гейт: на выдаче счётчик опрашивается",
          any("__IH_CB_COUNT" in c for c in calls), str(calls))

    # 5. падение рендера: перезапуск не более двух раз
    def pump(ms: int) -> None:
        deadline = time.time() + ms / 1000
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)

    ws.view = _StubView("https://ya.ru/images/search?text=cats")   # type: ignore[assignment]
    ws._reload_tries = 0
    bad = QWebEnginePage.RenderProcessTerminationStatus.AbnormalTerminationStatus
    ws._on_render_gone(bad, 777)
    check("падение рендера: счётчик попыток растёт", ws._reload_tries == 1)
    pump(1200)   # singleShot(1000, reload) успевает выстрелить
    check("падение рендера: перезапуск запланирован", "reload" in calls, str(calls))
    ws._on_render_gone(bad, 777)
    ws._on_render_gone(bad, 777)
    check("падение рендера: не больше двух попыток", ws._reload_tries == 2)
    normal = QWebEnginePage.RenderProcessTerminationStatus.NormalTerminationStatus
    ws._reload_tries = 0
    ws._on_render_gone(normal, 0)
    check("штатное завершение рендера не перезапускает вкладку",
          ws._reload_tries == 0)

    ws.deleteLater()
    app.processEvents()
    QTimer.singleShot(0, app.quit)   # чистим отложенные таймеры теста
    app.processEvents()


def main() -> int:
    test_detector()
    test_gpu_fix()
    test_qt_parts()
    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}: " + "; ".join(FAILURES))
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
