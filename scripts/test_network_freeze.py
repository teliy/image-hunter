"""Оффлайн-тест защиты от зависаний на сетевых дисках (v0.7.2).

Фон: у пользователя подвисало приложение на WebDAV-диске Z: — миниатюры и
полный просмотр читались через Qt-файловые операции, а открытие папки и
чтение подпапок дерева выполнялись прямо в GUI-потоке; на подвисшем
сервере это означало замирание всего процесса на сетевой тайм-аут (~60 с).

Проверяется:
* imgload читает файл обычным питоновским I/O (read_file_bytes) и декодирует
  из памяти: PNG декодируется, мусор/пустой файл/нет файла — честная ошибка;
* пока рабочие потоки «висят» на чтении «сетевых» файлов (FIFO-заглушки,
  open() блокируется как подвисший WebDAV), GUI-цикл продолжает отвечать —
  разрывы между тиками не превышают порога сторожа;
* открытие папки асинхронно: load_folder без entries возвращает управление
  сразу (скан в рабочем потоке), лента строится из сигнала, устаревший
  скан (папка сменилась) отбрасывается;
* чтение подпапок дерева асинхронно из клика (медленный scandir не держит
  GUI), синхронный вариант для фильтра работает;
* удаление файлов выполняется в рабочем потоке и обновляет ленту;
* формулировка «⏱ МЕДЛЕННО» зависит от потока: в GUI-потоке — «блокирует
  интерфейс», из рабочего — «фоном, интерфейс жив».

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_network_freeze.py
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

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from app.core import applog, i18n, imgload
from app.core.i18n import tr
from app.ui import local_viewer as lv

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


RECORDS: list[tuple[int, str]] = []


class _Capture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        RECORDS.append((record.levelno, record.getMessage()))


capture = _Capture()

QSettings("ImageHunter", "ImageHunter").clear()
i18n.set_lang("ru", persist=False)
applog.setup()
logging.getLogger("app").addHandler(capture)

HAS_FIFO = hasattr(os, "mkfifo")

# ---------- 1. imgload: чтение питоновским I/O + декод из памяти ----------

tmp = tempfile.mkdtemp(prefix="ih_netfreeze_")

src = QImage(200, 120, QImage.Format.Format_RGB32)
src.fill(0xFF204080)
png_path = os.path.join(tmp, "pic.png")
src.save(png_path, "PNG")

data, err = imgload.read_file_bytes(png_path)
check("read_file_bytes: читает файл", data is not None and not err, err)

img, err = imgload.load_file(png_path)
check("load_file(png): декодирует", not img.isNull() and not err
      and img.size() == src.size(), err or f"{img.width()}x{img.height()}")

img, err = imgload.load_file(png_path, max_side=64)
check("load_file(max_side): уменьшает", not img.isNull()
      and max(img.width(), img.height()) <= 64, err or f"{img.width()}x{img.height()}")

img, err = imgload.load_bytes(data, max_side=32)
check("load_bytes: декод из памяти", not img.isNull()
      and max(img.width(), img.height()) <= 32, err or f"{img.width()}x{img.height()}")

img, err = imgload.decode_bytes(data)
check("decode_bytes: обратная совместимость", not img.isNull() and not err, err)

bad_path = os.path.join(tmp, "garbage.png")
with open(bad_path, "wb") as f:
    f.write(b"\x00\x01\x02 not an image at all")
img, err = imgload.load_file(bad_path)
check("load_file(мусор): честная ошибка", img.isNull() and bool(err), err or "нет ошибки")

empty_path = os.path.join(tmp, "empty.png")
open(empty_path, "wb").close()
img, err = imgload.load_file(empty_path)
check("load_file(пустой): ошибка, не падение", img.isNull() and bool(err), err or "нет ошибки")

img, err = imgload.load_file(os.path.join(tmp, "нет_такого.png"))
check("load_file(нет файла): ошибка", img.isNull() and bool(err), err or "нет ошибки")

if imgload.AVIF_OK:
    import io as _io
    from PIL import Image as _Pil

    buf = _io.BytesIO()
    _Pil.new("RGB", (60, 40), (200, 10, 10)).save(buf, format="AVIF")
    img, err = imgload.load_bytes(buf.getvalue())
    check("load_bytes(AVIF): декод из памяти", not img.isNull() and not err,
          err or "null")

# ---------- 2. главный сценарий: рабочие потоки висят — GUI жив ----------

if HAS_FIFO:
    # FIFO ведёт себя как подвисший WebDAV-файл: open() блокируется, пока
    # не появится писатель. Скормим такие «картинки» вьюеру и замерим тики GUI.
    fifo_dir = tempfile.mkdtemp(prefix="ih_fifo_")
    fifos = []
    for i in range(6):
        p = os.path.join(fifo_dir, f"04152-YZZD1{'-' + str(i) if i else ''}.webp")
        os.mkfifo(p)
        fifos.append((p, 123, time.time()))

    w = lv.LocalViewer()
    w.resize(1200, 900)

    tick_gaps: list[float] = []
    last_tick = [time.monotonic()]

    def gui_beat():
        now = time.monotonic()
        tick_gaps.append(now - last_tick[0])
        last_tick[0] = now

    beat_timer = QTimer()
    beat_timer.setInterval(50)
    beat_timer.timeout.connect(gui_beat)
    beat_timer.start()

    def fifo_writer():
        time.sleep(2.0)                    # «сервер не отвечает»
        for p, _s, _m in fifos:            # потом «отвечает» — отдаёт мусор
            try:
                with open(p, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n junk")
            except OSError:
                pass

    threading.Thread(target=fifo_writer, daemon=True).start()

    t0 = time.perf_counter()
    w.load_folder(fifo_dir, entries=list(fifos))   # как после поиска: без скана
    elapsed = time.perf_counter() - t0
    check("load_folder(entries) мгновенен", elapsed < 0.5, f"{elapsed * 1000:.0f} мс")

    # крутим цикл событий, пока «сетевые» чтения висят (≈2 с) и чуть дольше
    end = time.monotonic() + 3.5
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)

    gaps_ms = [round(g * 1000) for g in tick_gaps[2:]]
    worst = max(gaps_ms) if gaps_ms else 0
    check("GUI не замирает, пока чтения висят", worst <= 400,
          f"макс. разрыв {worst} мс")
else:
    print("SKIP FIFO-сценарий: os.mkfifo недоступен (Windows)")

# ---------- 3. асинхронное открытие папки ----------

QSettings("ImageHunter", "ImageHunter").clear()
w2 = lv.LocalViewer()
folder = tempfile.mkdtemp(prefix="ih_scan_")
for i in range(3):
    QImage(20, 20, QImage.Format.Format_RGB32).save(os.path.join(folder, f"im{i}.png"),
                                                    "PNG")

real_scan = lv.scan_image_entries


def slow_scan(fol):
    time.sleep(0.6)                     # «сетевой» скан
    return real_scan(fol)


lv.scan_image_entries = slow_scan
t0 = time.perf_counter()
w2.load_folder(folder)                  # должен вернуть управление сразу
elapsed = time.perf_counter() - t0
check("load_folder без entries не ждёт скан", elapsed < 0.3,
      f"{elapsed * 1000:.0f} мс")
check("статус «Читаю папку…»", w2.status.text() == tr("viewer.folder_reading"),
      w2.status.text())

ok = wait_until(lambda: w2.list.count() == 3)
check("лента построена из фонового скана", ok, f"строк: {w2.list.count()}")
lv.scan_image_entries = real_scan

# устаревший скан отбрасывается: пока «медленный» скан первой папки висит,
# открываем вторую — результат первой не должен попасть в ленту
lv.scan_image_entries = slow_scan
folder_b = tempfile.mkdtemp(prefix="ih_scan_b_")
w2.load_folder(folder)                  # запустили медленный скан A
w2.load_folder(folder_b)                # тут же сменили папку (скан A устарел)
lv.scan_image_entries = real_scan       # скан B быстрый
ok = wait_until(lambda: w2._folder == folder_b and w2.list.count() == 0, 3.0)
time.sleep(1.2)                         # даём «медленному» скану A вернуться
app.processEvents()
check("устаревший скан отброшен", w2.list.count() == 0
      and os.path.normpath(w2._folder) == os.path.normpath(folder_b),
      f"строк: {w2.list.count()}, папка: {w2._folder}")

# ---------- 4. дерево: асинхронное чтение подпапок ----------

QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
w3 = lv.LocalViewer()

real_subdirs = lv.LocalViewer.__dict__["_list_subdirs"]
tree_root = tempfile.mkdtemp(prefix="ih_tree_")
EXPECTED = ["ALFA", "BETA", "GAMMA"]
for name in EXPECTED:
    os.mkdir(os.path.join(tree_root, name))


def fake_subdirs(path):
    time.sleep(0.4)                     # «сетевое» чтение подпапок
    return [os.path.join(tree_root, n) for n in EXPECTED]


lv.LocalViewer._list_subdirs = staticmethod(fake_subdirs)
top = None
for i in range(w3.tree.topLevelItemCount()):
    it = w3.tree.topLevelItem(i)
    if it.data(0, Qt.ItemDataRole.UserRole):
        top = it
        break

t0 = time.perf_counter()
w3._on_tree_clicked(top, 0)
elapsed = time.perf_counter() - t0
check("клик по узлу не ждёт scandir", elapsed < 0.3, f"{elapsed * 1000:.0f} мс")
check("узел получил жетон и заглушку", top.childCount() == 1
      and top.data(0, lv._TREE_TOKEN_ROLE) is not None)

ok = wait_until(lambda: top.childCount() == 3)
names = [top.child(j).text(0) for j in range(top.childCount())]
check("подпапки достроены из фона", ok and names == EXPECTED,
      f"дети: {names}")

# синхронный вариант — фильтр по-прежнему находит папки
lv.LocalViewer._list_subdirs = staticmethod(real_subdirs)
w3.folder_search.setText("BET")
ok = wait_until(lambda: w3.tree_info.text() == tr("viewer.folders_found", n=1), 6.0)
check("фильтр папок работает (синхронная догрузка)", ok, w3.tree_info.text())

# ---------- 5. удаление в рабочем потоке ----------

del_dir = tempfile.mkdtemp(prefix="ih_del_")
paths = []
for i in range(3):
    p = os.path.join(del_dir, f"del{i}.png")
    QImage(10, 10, QImage.Format.Format_RGB32).save(p, "PNG")
    paths.append(p)

w4 = lv.LocalViewer()
w4.load_folder(del_dir, entries=[(p, 10, 0.0) for p in paths])
wait_until(lambda: w4.list.count() == 3)
# выделяем все и удаляем навсегда (минуя диалог: вызываем фазы напрямую)
w4.list.selectAll()
w4._delete_perm = True
w4._start_delete(list(w4._paths), phase=2)
ok = wait_until(lambda: w4.list.count() == 0 and not os.path.exists(paths[0]), 8.0)
check("удаление в фоне: лента и диск пусты", ok,
      f"строк: {w4.list.count()}, файлов: {sum(os.path.exists(p) for p in paths)}")
check("статус после удаления", w4.status.text() == tr("viewer.del_done_perm", n=3),
      w4.status.text())
check("строки _paths обновлены", not w4._paths, str(len(w4._paths)))

# задача корзины (phase=1) на файле, которого нет, — честный провал в журнале
w4._start_delete([os.path.join(del_dir, "nope.png")], phase=1)
ok = wait_until(lambda: any(lvl == logging.ERROR and "nope.png" in m
                            for lvl, m in RECORDS), 8.0)
check("неудача удаления — в журнале", ok)

# ---------- 6. формулировки «⏱ МЕДЛЕННО» зависят от потока ----------

RECORDS.clear()
applog.slow_event("операция-из-gui", 999)
gui_hits = [m for _l, m in RECORDS if "операция-из-gui" in m]
check("из GUI-потока: «блокирует интерфейс»",
      bool(gui_hits) and "блокирует интерфейс" in gui_hits[0],
      gui_hits[0] if gui_hits else "нет строки")

RECORDS.clear()
holder = []


def worker_log():
    applog.slow_event("операция-из-воркера", 999)


th = threading.Thread(target=worker_log)
th.start()
th.join()
worker_hits = [m for _l, m in RECORDS if "операция-из-воркера" in m]
check("из рабочего потока: «фоном, интерфейс жив»",
      bool(worker_hits) and "фоном" in worker_hits[0]
      and "блокирует" not in worker_hits[0],
      worker_hits[0] if worker_hits else "нет строки")

# с by _Timed тоже
RECORDS.clear()


def slow_from_worker():
    with applog.timed("тихая-из-воркера", always=False, slow_ms=10):
        time.sleep(0.05)                # внутри блока: 50 мс > порога 10 мс


th = threading.Thread(target=slow_from_worker)
th.start()
th.join()
timed_hits = [m for _l, m in RECORDS if "тихая-из-воркера" in m]
check("timed() из воркера тоже «фоном»", bool(timed_hits) and "фоном" in timed_hits[0],
      timed_hits[0] if timed_hits else "нет строки")

# ---------- 7. i18n: новые ключи полны ----------

for key in ("log.event.timing_slow_worker", "viewer.folder_reading",
            "viewer.delete_busy"):
    row = i18n._STRINGS.get(key, {})
    check(f"i18n {key} (ru/en/zh)",
          all(row.get(l) for l in ("ru", "en", "zh")), str(sorted(row)))

print()
if FAILURES:
    print(f"ПРОВАЛЕНО: {len(FAILURES)} — " + "; ".join(FAILURES))
    os._exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
os._exit(0)
