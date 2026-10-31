"""Журнал работы Image Hunter: события приложения собираются в одном месте.

Мост «logging → Qt»: QtLogHandler пересылает записи модуля logging в
Qt-сигнал ``bridge.record(level, line)`` — вкладка «Журнал» подписана на
него и дописывает строки в текстовое поле. Записи из рабочих потоков
(поиск, загрузка, миниатюры) доезжают до интерфейса через очередь
сигналов, так что логировать можно откуда угодно — потокобезопасно.

Публичный интерфейс:

* ``setup()``            — подключить мост к корневому журналу (однократно);
* ``event(key, **p)``    — событие на языке интерфейса (строка из i18n);
* ``info/warning/error`` — обычные записи в журнал;
* ``timed(op, ...)``     — замер длительности блока: «⏱ операция: 123 мс»
  в журнале, при превышении порога — предупреждение оранжевым;
* ``extra(**kv)``        — хвост «[k=v]» для деталей замера.

Сторож GUI-потока (_UiWatchdog) замечает периоды, когда цикл событий не
отвечал, и пишет их длительность в журнал — по строкам ⏱ перед провалом
видно, какая операция его устроила.

Необработанные исключения тоже попадают в журнал (sys.excepthook) —
при разборе пользовательских отчётов видно, где именно упало.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback

from PySide6.QtCore import QObject, QTimer, Signal

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
    """Каждую запись logging отправляет в Qt-сигнал для вкладки «Журнал».

    Записи из посторонних потоков помечаются именем потока в конце строки —
    при разборе зависаний сразу видно, какая строка пришла не из интерфейса.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:                     # форматирование не должно ронять поток
            return
        tname = record.threadName or ""
        if tname and tname != "MainThread":
            line = f"{line} [{tname}]"
        bridge.record.emit(record.levelno, line)


def level_tag(level: int) -> str:
    """Короткая метка уровня для строки журнала (DEBUG/INFO/WARN/ERROR)."""
    return _LEVEL_TAG.get(level, "INFO")


_handler: QtLogHandler | None = None
_watchdog: "_UiWatchdog | None" = None


def setup(level: int = logging.INFO) -> None:
    """Подключить мост к корневому журналу и хук необработанных исключений.

    Здесь же запускается сторож GUI-потока: он пишет в журнал, если цикл
    событий перестал отвечать (см. _UiWatchdog). Работает только после
    создания QApplication — до этого вызов setup() просто не запускает его.
    """
    global _handler, _watchdog
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
    from PySide6.QtWidgets import QApplication   # лениво: QtCore-импорт тяжеловат
    if QApplication.instance() is not None and _watchdog is None:
        _watchdog = _UiWatchdog()
        _watchdog.start()
        _log(logging.INFO, _tr("log.event.watchdog_on"))


def _excepthook(exc_type, exc, tb) -> None:
    """Необработанное исключение — в журнал, затем штатный хвост (stderr)."""
    logging.getLogger(_APP_LOGGER).critical(
        "Необработанное исключение: %s\n%s",
        exc_type.__name__, "".join(traceback.format_exception(exc_type, exc, tb)),
    )
    sys.__excepthook__(exc_type, exc, tb)


def _tr(key: str, **params) -> str:
    """Перевод ключа i18n (ленивый импорт — i18n не должен тянуть сюда цикл)."""
    from app.core.i18n import tr
    return tr(key, **params)


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
    _log(logging.INFO, _tr(key, **params))


# ---------- отладка производительности: сколько длилась операция ----------


def extra(**kv) -> str:
    """Хвост строки журнала «[k=v, k2=v2]» для деталей замера."""
    if not kv:
        return ""
    return " [" + ", ".join(f"{k}={v}" for k, v in kv.items()) + "]"


class _Timed:
    """Замер длительности операции со строкой в «Журнале».

    Использование::

        with applog.timed(tr("perf.op.scan_folder")) as t:
            entries = scan_image_entries(folder)
            t.set(files=len(entries))

    По выходе из блока в журнал уходит «⏱ сканирование папки: 123 мс
    [files=45]». Параметры:

    * ``slow_ms`` — порог «медленной» операции: превышение перекрашивает
      строку в предупреждение (в журнале — оранжевым, сразу заметно);
    * ``always=False`` — писать строку только для медленных операций или
      после ``t.force()`` (для мелких частых действий, чтобы не шуметь);
    * при исключении внутри блока время всё равно попадёт в журнал —
      с пометкой ``error=ИмяИсключения``, само исключение летит дальше.
    """

    __slots__ = ("_op", "_slow_ms", "_always", "_forced", "_kv", "_t0")

    def __init__(self, op: str, slow_ms: int | None = None,
                 always: bool = True, **kv) -> None:
        self._op = op
        self._slow_ms = slow_ms
        self._always = always
        self._forced = False
        self._kv: dict[str, object] = dict(kv)
        self._t0 = 0.0

    def set(self, **kv) -> None:
        """Дополнить строку деталями, ставшими известными внутри блока."""
        self._kv.update(kv)

    def force(self) -> None:
        """Пометить замер как стоящий строки, даже если операция быстрая."""
        self._forced = True

    def __enter__(self) -> "_Timed":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = round((time.perf_counter() - self._t0) * 1000)
        if exc_type is not None:
            self._kv["error"] = exc_type.__name__
            self._always = True
            self._slow_ms = None
        slow = self._slow_ms is not None and ms >= self._slow_ms
        if not (self._always or self._forced or slow or exc_type is not None):
            return False          # быстрая рутина — журнал не засоряем
        key = "log.event.timing_slow" if slow else "log.event.timing"
        level = logging.WARNING if slow else logging.ERROR if exc_type else logging.INFO
        _log(level, _tr(key, op=self._op, ms=ms, extra=extra(**self._kv)))
        return False


def timed(op: str, slow_ms: int | None = None,
          always: bool = True, **kv) -> _Timed:
    """Замерить длительность блока и написать её в «Журнал» (см. _Timed)."""
    return _Timed(op, slow_ms=slow_ms, always=always, **kv)


class _UiWatchdog(QObject):
    """Сторож отзывчивости интерфейса — прямой ответ на «программа зависла».

    Раз в INTERVAL_MS таймер требует тик в GUI-потоке. Если тик пришёл
    с опозданием больше LATE_THRESHOLD_MS — цикл событий не отвечал
    (какая-то операция держала GUI-поток), и в журнал уходит предупреждение
    с примерной длительностью зависания. Так по журналу видно, КАКОЙ
    операции предшествовал провал и сколько он длился, даже когда сам
    пользователь запомнил только «программа подвисла».
    """

    INTERVAL_MS = 250
    LATE_THRESHOLD_MS = 700

    def __init__(self) -> None:
        super().__init__()
        self._last = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._last = time.monotonic()
        self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        late_ms = round((now - self._last) * 1000) - self.INTERVAL_MS
        self._last = now
        if late_ms > self.LATE_THRESHOLD_MS:
            _log(logging.WARNING, _tr("log.event.ui_freeze", ms=late_ms))
