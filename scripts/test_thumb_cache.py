"""Оффлайн-тест кэша миниатюр и скорости сканирования папок.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_thumb_cache.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer, QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from app.ui import local_viewer as lv  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_image(path: str, w: int = 400, h: int = 300, color: int = 0x336699) -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    assert img.save(path)


def wait_thumbs(viewer, app, n, done_before):
    deadline = 0
    while viewer._thumbs_done < done_before + n and deadline < 400:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()
        deadline += 1
    return viewer._thumbs_done >= done_before + n


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)  # изолируем тесты
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    viewer = lv.LocalViewer()
    viewer.resize(1700, 1200)
    viewer.show()   # ленивые миниатюры: грузятся только видимые строки
    cache_dir = lv._thumb_cache_dir()
    check("кэш-каталог создан", bool(cache_dir), cache_dir)

    tmp = tempfile.mkdtemp(prefix="ih_cache_")
    try:
        n = 12
        for i in range(n):
            make_image(os.path.join(tmp, f"pic_{i:02d}.png"))

        # 1. первое открытие: холодный кэш, миниатюры создаются
        t0 = time.perf_counter()
        viewer.load_folder(tmp)
        ok = wait_thumbs(viewer, app, n, 0)
        t_cold = time.perf_counter() - t0
        check("первое открытие: все миниатюры готовы", ok, f"{t_cold:.2f} с")
        cached = [f for f in os.listdir(cache_dir) if f.endswith(".png")]
        check("миниатюры сохранены в кэш", len(cached) >= n, f"{len(cached)} файлов")

        # 2. повторное открытие: всё из кэша (на сетевом диске это главный выигрыш)
        viewer._pool.waitForDone(10000)
        t0 = time.perf_counter()
        viewer.load_folder(tmp)
        ok = wait_thumbs(viewer, app, n, viewer._thumbs_done)
        t_warm = time.perf_counter() - t0
        check("повторное открытие: все миниатюры готовы", ok, f"{t_warm:.2f} с")
        check("повторное открытие заметно быстрее", t_warm < t_cold or t_cold < 0.3,
              f"{t_cold:.2f} с → {t_warm:.2f} с")

        # 3. смена папки на лету: старые задачи не портят новую папку (gen-защита)
        tmp2 = tempfile.mkdtemp(prefix="ih_cache2_")
        make_image(os.path.join(tmp2, "only_one.jpg"))
        viewer.load_folder(tmp2)  # сразу, не дожидаясь задач из tmp
        wait_thumbs(viewer, app, 1, viewer._thumbs_done)
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()
        check("смена папки: в списке ровно 1 файл", viewer.list.count() == 1,
              f"count={viewer.list.count()}")
        check("смена папки: миниатюра нужного файла",
              viewer.list.item(0).text() == "only_one.jpg")
        shutil.rmtree(tmp2, ignore_errors=True)

        # 4. перезаписанный файл получает новую миниатюру (ключ по mtime/размеру)
        p = os.path.join(tmp, "pic_00.png")
        entries = {e[0]: e for e in lv.scan_image_entries(tmp)}
        before_key = lv._thumb_cache_key(p, entries[p][1], entries[p][2])
        time.sleep(0.02)
        make_image(p, w=320, h=240, color=0xFF8800)  # перезапись: другой размер и mtime
        entries2 = {e[0]: e for e in lv.scan_image_entries(tmp)}
        after_key = lv._thumb_cache_key(p, entries2[p][1], entries2[p][2])
        check("перезапись файла меняет ключ кэша", before_key != after_key)

        # 5. скорость сканирования папки с большим числом файлов (один проход scandir)
        big = tempfile.mkdtemp(prefix="ih_big_")
        for i in range(2000):
            open(os.path.join(big, f"f_{i:04d}.jpg"), "wb").close()
        for i in range(500):
            open(os.path.join(big, f"x_{i:04d}.txt"), "wb").close()
        t0 = time.perf_counter()
        found = lv.scan_image_entries(big)
        dt = time.perf_counter() - t0
        check("сканирование 2500 файлов нашло 2000 картинок", len(found) == 2000,
              f"{dt * 1000:.0f} мс")
        shutil.rmtree(big, ignore_errors=True)

        # 6. ленивая загрузка: при входе в большую папку НЕ стартуют задачи на все файлы
        lazy = tempfile.mkdtemp(prefix="ih_lazy_")
        for i in range(300):
            make_image(os.path.join(lazy, f"L_{i:03d}.png"), w=64, h=64)
        viewer.load_folder(lazy)
        for _ in range(40):   # ждём срабатывания таймера видимых строк (~120 мс)
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()
        queued = len(viewer._thumb_queued)
        check("ленивая загрузка: задачи только для видимых (не все 300)",
              0 < queued < 300, f"очередь={queued} из 300")
        shutil.rmtree(lazy, ignore_errors=True)

        print(f"\nвремя: холодное открытие {t_cold:.2f} с, из кэша {t_warm:.2f} с, "
              f"скан 2500 файлов {dt * 1000:.0f} мс")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
