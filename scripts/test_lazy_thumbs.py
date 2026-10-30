"""Оффлайн-тест ленивой загрузки миниатюр (только видимые строки).

Проверяет, что массовая прогрузка предпросмотра отключена: при входе в папку
с тысячей файлов задачи миниатюр ставятся только для видимой части списка,
при прокрутке догружаются новые видимые, а выключатель «Миниатюры» полностью
останавливает загрузку.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_lazy_thumbs.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui import local_viewer as lv  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_image(path: str, w: int = 48, h: int = 36, color: int = 0x336699) -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    assert img.save(path)


def make_folder(n: int, prefix: str = "ih_lz_") -> str:
    d = tempfile.mkdtemp(prefix=prefix)
    for i in range(n):
        make_image(os.path.join(d, f"p_{i:04d}.png"))
    return d


def pump(app, ms: int = 400) -> None:
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)  # изолируем тесты

    viewer = lv.LocalViewer()
    viewer.resize(420, 560)   # узкое окно: видно несколько строк из сотен
    viewer.show()

    folder = make_folder(120)
    try:
        # 1. вход в папку: задачи не на все 120 файлов, а только на видимые
        viewer.load_folder(folder)
        pump(app, 700)
        queued = len(viewer._thumb_queued)
        check("вход в папку: очередь меньше сотни (не массовая прогрузка)",
              0 < queued < 120, f"очередь={queued} из 120")
        ok = wait_done(viewer, app, queued)
        check("видимые миниатюры реально загрузились", ok,
              f"done={viewer._thumbs_done} из очереди {queued}")

        # 2. прокрутка в конец: догрузились новые видимые, прежние не пере-ставились
        sb = viewer.list.verticalScrollBar()
        queued_before = queued
        sb.setValue(sb.maximum())
        pump(app, 700)
        check("прокрутка догружает новые видимые строки",
              len(viewer._thumb_queued) > queued_before,
              f"очередь {queued_before} → {len(viewer._thumb_queued)}")
        ok = wait_done(viewer, app, len(viewer._thumb_queued))
        check("после прокрутки все новые миниатюры загрузились", ok,
              f"done={viewer._thumbs_done}")

        # обратная прокрутка вверх: верхние строки уже готовы — новых задач нет
        queued_mid = len(viewer._thumb_queued)
        sb.setValue(0)
        pump(app, 500)
        check("обратная прокрутка не пере-ставляет готовые строки",
              len(viewer._thumb_queued) == queued_mid,
              f"очередь {queued_mid} → {len(viewer._thumb_queued)}")

        # 3. выключатель «Миниатюры»: выкл — задачи больше не ставятся
        viewer._pool.waitForDone(10000)
        pump(app, 300)
        viewer.btn_thumbs.setChecked(False)
        pump(app, 300)
        done_off = viewer._thumbs_done
        sb.setValue(0)                    # скроллим при выключенном предпросмотре
        pump(app, 700)
        check("выключатель: при скролле задач нет",
              viewer._thumbs_done == done_off and not viewer._thumb_queued,
              f"done={done_off} → {viewer._thumbs_done}")
        check("состояние выключателя сохранено в настройках",
              viewer._thumbs_enabled is False)

        # 4. включили обратно: недостающие строки догрузились
        done_before_on = viewer._thumbs_done
        viewer.btn_thumbs.setChecked(True)
        sb.setValue(sb.maximum() // 2)   # уходим в середину — там ещё нет миниатюр
        pump(app, 700)
        check("включатель: догрузка возобновилась", len(viewer._thumb_queued) > 0,
              f"очередь={len(viewer._thumb_queued)}")
        ok = wait_done(viewer, app, done_before_on + len(viewer._thumb_queued))
        check("после повторного включения миниатюры загрузились", ok,
              f"done={viewer._thumbs_done}")

        # 5. смена папки: задачи прошлой папки не портят новую (gen-защита)
        sb.setValue(sb.maximum())
        pump(app, 100)
        folder2 = make_folder(1, prefix="ih_lz2_")
        viewer.load_folder(folder2)      # сразу, не дожидаясь задач folder
        pump(app, 700)
        check("смена папки: в списке ровно 1 файл", viewer.list.count() == 1,
              f"count={viewer.list.count()}")
        check("смена папки: очередь очищена от прошлой папки",
              len(viewer._thumb_queued) <= 1,
              f"очередь={len(viewer._thumb_queued)}")
        shutil.rmtree(folder2, ignore_errors=True)

        # 6. выключатель не мешает построению списка (без чтения файлов)
        viewer.btn_thumbs.setChecked(False)
        viewer.load_folder(folder)
        pump(app, 400)
        check("с выключенными миниатюрами список всё равно построен",
              viewer.list.count() == 120, f"count={viewer.list.count()}")
        check("с выключенными миниатюрами задач нет", not viewer._thumb_queued)

        print("\nленивая загрузка: очередь на входе —", queued, "из 120")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


def wait_done(viewer, app, target: int, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if viewer._thumbs_done >= target:
            time.sleep(0.05)
            app.processEvents()
            return True
        time.sleep(0.02)
    return False


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
