"""Единый модуль настройки и защиты QtWebEngine — «быстро и без зависаний».

Всё, что касается встроенного браузера на уровне окружения, собрано здесь,
а не размазано по точке входа и вкладкам:

1. Ловля предупреждений Qt о платформенных плагинах (поломанный Wayland);
2. Автофлаги Chromium против зависаний:
   * ``--disable-gpu``          — когда Wayland-плагин не загрузился (гибрид
                                  Qt-on-XWayland + GPU-процесс Chromium
                                  deadlock'ится с драйвером — окно висит целиком);
   * ``--disable-dev-shm-usage``— разделяемая память вместо /dev/shm: на
                                  системах с крошечным /dev/shm вкладки
                                  молча падали и перезапускались по кругу;
   * ``--disable-breakpad``     — Chromium не тратит время на дампы крахов;
   * ``--no-sandbox``           — ТОЛЬКО когда ядро запрещает пользовательские
                                  пространства имён (иначе render-процессы
                                  циклически падают и вкладка «серая»);
3. Watchdog загрузки: страница, которая не открылась за 45 секунд
   (мёртвая сеть, зависший редирект), останавливается программно —
   вкладка никогда не крутит «вечную загрузку».

Переопределения через переменные окружения:
* ``IH_GPU=0``     — выключить GPU принудительно (даже если Wayland в порядке);
* ``IH_GPU=1``     — оставить GPU включённым, автодетект игнорировать;
* ``IH_NO_SANDBOX=1`` — выключить песочницу принудительно;
* ``IH_NO_SANDBOX=0`` — никогда не выключать песочницу автоматически;
* свои ``QTWEBENGINE_CHROMIUM_FLAGS`` дополняются, а не затираются.
"""

from __future__ import annotations

import os
import sys

# Таймаут «вечной» загрузки страницы: после него загрузка останавливается.
LOAD_TIMEOUT_MS = 45_000

# Предупреждения Qt о платформенных плагинах печатаются при создании
# QApplication — ловим их, чтобы понять окружение ДО первого окна.
_qpa_warnings: list[str] = []


def capture_qpa_warnings() -> None:
    """Запоминать предупреждения Qt о платформенных плагинах (см. выше)."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def handler(mode, _context, message) -> None:
            if mode == QtMsgType.QtWarningMsg and "platform plugin" in str(message):
                _qpa_warnings.append(str(message))

        qInstallMessageHandler(handler)
    except Exception:
        pass    # диагностика не должна мешать запуску


def wayland_fallback_failed(messages: list[str] | None = None) -> bool:
    """Сессия Wayland, но Qt-плагин wayland не загрузился (или не найден).

    Ровно этот случай виден в пользовательских отчётах строкой
    ``Could not load the Qt platform plugin "wayland" … even though it was
    found``: приложение продолжает работать через xcb (XWayland), но
    связка «QtWebEngine + графический драйвер» на таком гибриде известна
    зависаниями всего окна (тот же класс проблем, что у Anki и других
    QtWebEngine-программ).
    """
    msgs = _qpa_warnings if messages is None else messages
    for m in msgs:
        if "wayland" not in m:
            continue
        if ("Could not load the Qt platform plugin" in m
                or "Could not find the Qt platform plugin" in m):
            return True
    return False


def _user_namespaces_disabled() -> bool:
    """Ядро Linux запрещает пользовательские пространства имён?

    Без них песочница Chromium не может запустить render-процессы: вкладки
    падают и перезапускаются по кругу, интерфейс выглядит зависшим. Такое
    встречается на серверных/старых ядрах (unprivileged_userns_clone = 0).
    """
    for path in ("/proc/sys/kernel/unprivileged_userns_clone",
                 "/proc/sys/user/max_user_namespaces"):
        try:
            with open(path, encoding="ascii") as fh:
                if fh.read().strip() in ("0",):
                    return True
        except OSError:
            continue
    return False


def _add_flags(extra: str) -> None:
    """Дописать флаги Chromium к QTWEBENGINE_CHROMIUM_FLAGS (без дублей)."""
    cur = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    out = cur
    for flag in extra.split():
        if flag and flag not in out:
            out = (out + " " + flag).strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = out


def _linux_base_flags() -> list[str]:
    """Базовые флаги устойчивости на Linux (безопасны на любой системе)."""
    if sys.platform != "linux":
        return []
    flags = ["--disable-dev-shm-usage", "--disable-breakpad"]
    override = os.environ.get("IH_NO_SANDBOX", "").strip()
    if override == "1" or (override != "0" and _user_namespaces_disabled()):
        flags.append("--no-sandbox")
    return flags


def apply_gpu_fix() -> bool:
    """Выключить GPU у встроенного браузера, если окружение склонно к зависаниям.

    Программный рендеринг страниц выдачи на современном процессоре незаметен,
    зато исключает целый класс зависаний, когда GPU-процесс Chromium
    deadlock'ится с драйвером (окно перестаёт отвечать целиком).
    Возвращает True, если GPU выключен.
    """
    override = os.environ.get("IH_GPU", "").strip()
    if override == "1":
        return False
    if not (override == "0" or wayland_fallback_failed()):
        return False
    _add_flags("--disable-gpu")
    return True


def apply_env_fixes() -> dict:
    """Применить все флаги защиты. Вызывать ПОСЛЕ QApplication (предупреждения
    Qt о плагинах уже пойманы) и ДО создания первого WebEngine-объекта.

    Возвращает сводку решений: {"gpu_off": bool, "sandbox_off": bool} —
    для событий журнала после старта applog.
    """
    gpu_off = apply_gpu_fix()
    sandbox_off = False
    for flag in _linux_base_flags():
        if flag == "--no-sandbox":
            sandbox_off = True
        _add_flags(flag)
    return {"gpu_off": gpu_off, "sandbox_off": sandbox_off}


# ---------------- watchdog «вечной» загрузки ----------------

def _watchdog_fire(view) -> None:
    """Страница не открылась за отведённое время — остановить загрузку.

    Без остановки вкладка остаётся в состоянии «грузится» до перезапуска
    программы (типично для мёртвой сети или зависшего редиректа), а
    пользователь считает, что программа зависла.
    """
    try:
        url = view.url().toString()
        view.stop()
        from app.core import applog
        applog.event("log.event.load_watchdog", sec=LOAD_TIMEOUT_MS // 1000, url=url)
    except Exception:
        pass    # защита не должна сама становиться источником ошибок


def attach_load_watchdog(view):
    """Повесить на QWebEngineView сторожевой таймер загрузки.

    loadStarted — таймер пошёл; loadFinished — сброшен; если страница не
    завершилась за LOAD_TIMEOUT_MS, ``_watchdog_fire`` останавливает её.
    Возвращает таймер (владелец — сам view, отдельно хранить не нужно).
    """
    from PySide6.QtCore import QTimer

    timer = QTimer(view)
    timer.setObjectName("ih-load-watchdog")
    timer.setSingleShot(True)
    timer.setInterval(LOAD_TIMEOUT_MS)
    timer.timeout.connect(lambda: _watchdog_fire(view))
    view.loadStarted.connect(timer.start)
    view.loadFinished.connect(timer.stop)
    return timer
