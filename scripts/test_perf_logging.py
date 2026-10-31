"""Оффлайн-тест отладочной телеметрии журнала и яркой подсветки выделения (v0.7.1).

Проверяется: замер длительности applog.timed (обычный/медленный/тихий/
принудительный/с исключением), тег постороннего потока в строках журнала,
сторож GUI-потока (_UiWatchdog) отмечает подвисание, полнота i18n новых
ключей (ru/en/zh), стиль выделения применяется к приложению, Ctrl+A на
ленте миниатюр выделяет всё и пишет в журнал.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_perf_logging.py
"""

import logging
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)          # QApplication до applog.setup() — включится сторож

from app import __version__
from app.core import applog, i18n
from app.core.i18n import tr
from app.ui.style import SELECTION_QSS, apply_app_style

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


# ---------- приём строк журнала ----------

RECORDS: list[tuple[int, str]] = []


class _Capture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        RECORDS.append((record.levelno, record.getMessage()))


capture = _Capture()

QSettings("ImageHunter", "ImageHunter").clear()
i18n.set_lang("ru", persist=False)   # проверки текста — на русском, независимо от локали песочницы
applog.setup()
logging.getLogger("app").addHandler(capture)

check("версия 0.7.1", __version__ == "0.7.1", __version__)
check("setup подключил хендлер", applog._handler is not None)
check("сторож запущен после setup", applog._watchdog is not None)

# ---------- замер длительности: обычный блок ----------

RECORDS.clear()
with applog.timed("тест-операция", files=3) as t:
    time.sleep(0.03)
    t.set(rows=2)
hits = [(lvl, msg) for lvl, msg in RECORDS if "тест-операция" in msg]
check("timed пишет одну строку", len(hits) == 1, str(len(hits)))
if hits:
    lvl, msg = hits[0]
    check("timed уровень INFO", lvl == logging.INFO, logging.getLevelName(lvl))
    check("timed содержит длительность", "мс" in msg, msg)
    check("timed содержит детали блока", "[files=3, rows=2]" in msg, msg)
    ms_part = msg.split("тест-операция: ")[1].split(" ")[0] if "тест-операция: " in msg else ""
    check("timed длительность правдоподобна", ms_part.isdigit() and int(ms_part) >= 25, msg)

# ---------- замер длительности: медленная операция ----------

RECORDS.clear()
with applog.timed("медленная-операция", slow_ms=50):
    time.sleep(0.12)
slow_hits = [(lvl, msg) for lvl, msg in RECORDS if "медленная-операция" in msg]
check("медленная операция пишет WARN", bool(slow_hits)
      and slow_hits[0][0] == logging.WARNING,
      logging.getLevelName(slow_hits[0][0]) if slow_hits else "нет строк")
if slow_hits:
    check("медленная помечена МЕДЛЕННО", "МЕДЛЕННО" in slow_hits[0][1], slow_hits[0][1])

# ---------- тихие замеры: без строки; force() пробуждает ----------

RECORDS.clear()
with applog.timed("тихая-операция", always=False, slow_ms=100000):
    pass
check("тихая быстрая операция не пишет", not any("тихая-операция" in m for _l, m in RECORDS))
with applog.timed("принудительная", always=False) as t2:
    t2.force()
check("force() пробуждает строку", any("принудительная" in m for _l, m in RECORDS))

# ---------- исключение внутри блока ----------

RECORDS.clear()
raised = False
try:
    with applog.timed("падающая-операция"):
        raise ValueError("бум")
except ValueError:
    raised = True
check("исключение пролетает дальше", raised)
check("исключение попало в журнал", any("падающая-операция" in m and "error=ValueError" in m
                                        for _l, m in RECORDS),
      str(RECORDS))

# ---------- тег постороннего потока в строках журнала ----------

BRIDGE_LINES: list[str] = []
applog.bridge.record.connect(lambda _lvl, line: BRIDGE_LINES.append(line))
logging.getLogger("app").warning("строка-главного-потока")


def _from_thread() -> None:
    logging.getLogger("app").warning("строка-из-потока")


worker = threading.Thread(target=_from_thread, name="ТестПоток")
worker.start()
worker.join()
check("строки моста дошли", wait_until(lambda: len(BRIDGE_LINES) >= 2), str(len(BRIDGE_LINES)))
if len(BRIDGE_LINES) >= 2:
    main_line = next((x for x in BRIDGE_LINES if "строка-главного-потока" in x), "")
    thread_line = next((x for x in BRIDGE_LINES if "строка-из-потока" in x), "")
    check("главный поток без тега", main_line and "[ТестПоток]" not in main_line
          and "[Thread" not in main_line, main_line)
    check("посторонний поток помечен", thread_line and "[ТестПоток]" in thread_line, thread_line)

# ---------- сторож GUI-потока ----------

RECORDS.clear()
wd = applog._UiWatchdog()
wd._last = time.monotonic() - 2.5     # «тик» пришёл с опозданием 2,25 с
wd._tick()
freeze_text = tr("log.event.ui_freeze", ms=2250)
freeze_hits = [(lvl, msg) for lvl, msg in RECORDS if "не отвечал" in msg]
check("сторож отметил подвисание", bool(freeze_hits)
      and freeze_hits[0][0] == logging.WARNING,
      logging.getLevelName(freeze_hits[0][0]) if freeze_hits else "нет строк")
if freeze_hits:
    check("в сообщении длительность", "2250" in freeze_hits[0][1], freeze_hits[0][1])
    check("текст совпадает с i18n", freeze_hits[0][1].endswith(freeze_text),
          freeze_hits[0][1])
RECORDS.clear()
wd._last = time.monotonic() - 0.05    # тик пришёл вовремя
wd._tick()
check("вовремя пришедший тик молчит", not any("не отвечал" in m for _l, m in RECORDS))

# ---------- полнота i18n новых ключей ----------

TIMING_KEYS = ["log.event.timing", "log.event.timing_slow", "log.event.ui_freeze",
               "log.event.watchdog_on", "log.event.select_all"]
PERF_KEYS = [k for k in i18n._STRINGS if k.startswith("perf.op.")]
check("появились имена операций", len(PERF_KEYS) >= 15, str(len(PERF_KEYS)))
for key in TIMING_KEYS + PERF_KEYS:
    entry = i18n._STRINGS.get(key, {})
    ok = all(entry.get(lang) for lang in ("ru", "en", "zh"))
    check(f"i18n {key}", ok, str(sorted(entry)))

# ---------- стиль выделения применяется к приложению ----------

check("стиль содержит синий выделения", "#1565d8" in SELECTION_QSS)
apply_app_style(app)
qss = app.styleSheet()
check("стиль установлен на приложение", "#1565d8" in qss and "QTreeWidget::item:selected" in qss)
check("стиль покрывает список/дерево/таблицу",
      all(sel in qss for sel in ("QListWidget::item:selected", "QTreeView::item:selected",
                                 "QTableWidget::item:selected")))
check("есть состояние неактивного окна", ":selected:!active" in qss)

# ---------- Ctrl+A на ленте миниатюр ----------

tmp = tempfile.mkdtemp(prefix="ih_perf_")
for i in range(3):
    from PySide6.QtGui import QImage
    img = QImage(24, 24, QImage.Format_RGB32)
    img.fill(0x4488cc)
    check(f"файл {i} записан", img.save(os.path.join(tmp, f"img{i}.png")))

from app.ui.local_viewer import LocalViewer  # noqa: E402 — после создания QApplication

v = LocalViewer()
RECORDS.clear()
v.load_folder(tmp)
check("лента наполнена", v.list.count() == 3, str(v.list.count()))
check("открытие папки замерено",
      any(tr("perf.op.load_folder") in m for _l, m in RECORDS),
      str(RECORDS[:4]))
check("сканирование папки замерено",
      any(tr("perf.op.scan_folder") in m for _l, m in RECORDS), "")

RECORDS.clear()
v._select_all_files()
app.processEvents()
check("Ctrl+A выделил все плитки", len(v.list.selectedItems()) == 3,
      str(len(v.list.selectedItems())))
check("Ctrl+A отмечен в журнале",
      any(tr("log.event.select_all", n=3) in m for _l, m in RECORDS),
      str(RECORDS[-3:] if RECORDS else []))

print()
print(f"Итого проверок с ошибками: {len(FAILURES)}")
for name in FAILURES:
    print(f"  FAIL {name}")
sys.stdout.flush()
os._exit(1 if FAILURES else 0)
