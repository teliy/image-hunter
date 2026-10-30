"""Журнал работы Image Hunter: события приложения собираются в одном месте.

Мост «logging → Qt»: QtLogHandler пересылает записи модуля logging в
Qt-сигнал ``bridge.record(level, line)`` — вкладка «Журнал» подписана на
него и дописывает строки в текстовое поле. Записи из рабочих потоков
(поиск, загрузка, миниатюры) доезжают до интерфейса через очередь
сигналов, так что логировать можно откуда угодно — потокобезопасно.

Публичный интерфейс:

* ``setup()``            — подключить мост к корневому журналу (однократно);
* ``event(key, **p)``    — событие на языке интерфейса (строка из i18n);
* ``info/warning/error`` — обычные записи в журнал.

Необработанные исключения тоже попадают в журнал (sys.excepthook) —
при разборе пользовательских отчётов видно, где именно упало.
"""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QObject, Signal

_APP_LOGGER = "app"

_LEVEL_TAG = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "ERROR",
}


class _Bridge(QObject):
    """Пересылает готовые строки журнала в интерфейс (GUI-поток)."""

    record = Signal(int, str)      # уровень, строка «ЧЧ:ММ:СС текст»


bridge = _Bridge()


class QtLogHandler(logging.Handler):
    """Каждую запись logging отправляет в Qt-сигнал для вкладки «Журнал»."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:                     # форматирование не должно ронять поток
            return
        bridge.record.emit(record.levelno, line)


def level_tag(level: int) -> str:
    """Короткая метка уровня для строки журнала (DEBUG/INFO/WARN/ERROR)."""
    return _LEVEL_TAG.get(level, "INFO")


_handler: QtLogHandler | None = None


def setup(level: int = logging.INFO) -> None:
    """Подключить мост к корневому журналу и хук необработанных исключений."""
    global _handler
    if _handler is not None:
        return
    _handler = QtLogHandler()
    root = logging.getLogger()
    root.setLevel(level)
    # сторонние библиотеки не должны заваливать журнал отладкой
    for noisy in ("urllib3", "requests", "PIL", "chardet", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root.addHandler(_handler)
    sys.excepthook = _excepthook


def _excepthook(exc_type, exc, tb) -> None:
    """Необработанное исключение — в журнал, затем штатный хвост (stderr)."""
    logging.getLogger(_APP_LOGGER).critical(
        "Необработанное исключение: %s\n%s",
        exc_type.__name__, "".join(traceback.format_exception(exc_type, exc, tb)),
    )
    sys.__excepthook__(exc_type, exc, tb)


def _log(level: int, text: str) -> None:
    logging.getLogger(_APP_LOGGER).log(level, text)


def debug(text: str) -> None:
    _log(logging.DEBUG, text)


def info(text: str) -> None:
    _log(logging.INFO, text)


def warning(text: str) -> None:
    _log(logging.WARNING, text)


def error(text: str) -> None:
    _log(logging.ERROR, text)


def event(key: str, **params) -> None:
    """Событие на языке интерфейса: текст берётся из i18n по ключу."""
    from app.core.i18n import tr
    _log(logging.INFO, tr(key, **params))
