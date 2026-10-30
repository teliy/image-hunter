"""Оффлайн-тест растягивания панели миниатюр и порядка кнопок в тулбаре.

Проверяет жалобы пользователя:
1) панель миниатюр расширяется мышью (за разделитель сплиттера);
2) новая ширина запоминается между запусками;
3) поле поиска стоит ПОСЛЕ кнопки «Показать в проводнике».

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_resize_panel.py
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
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from app.ui import local_viewer as lv  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def pump(app, ms: int = 400) -> None:
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").remove("viewer/splitter")  # детерминизм

    tmp = tempfile.mkdtemp(prefix="ih_resize_")
    try:
        for i in range(300):
            img = QImage(48, 36, QImage.Format.Format_RGB32)
            img.fill(0x336699)
            assert img.save(os.path.join(tmp, f"r_{i:03d}.png"))

        # --- порядок кнопок в тулбаре ---
        viewer = lv.LocalViewer()
        viewer.resize(1200, 800)
        viewer.show()
        pump(app, 300)

        bar_lay = viewer.layout().itemAt(0).layout()
        widgets = [w for w in (bar_lay.itemAt(i).widget() for i in range(bar_lay.count()))
                   if w is not None]  # распорки (spacers) не считаем
        reveal_idx = next(
            (i for i, w in enumerate(widgets)
             if isinstance(w, QToolButton) and "проводнике" in w.text().lower()), -1)
        check("кнопка переименована в «Показать в проводнике»", reveal_idx >= 0)
        search_idx = widgets.index(viewer.search_edit) if viewer.search_edit in widgets else -1
        check("поле поиска стоит после кнопки «Показать в проводнике»",
              reveal_idx >= 0 and search_idx == reveal_idx + 1,
              f"кнопка #{reveal_idx}, поиск #{search_idx}")

        # --- ширина ленты больше не зафиксирована ---
        check("минимальная ширина ленты = THUMB+34",
              viewer.list.minimumWidth() == lv.THUMB + 34,
              f"{viewer.list.minimumWidth()}")
        check("максимальная ширина не ограничена (растягивается)",
              viewer.list.maximumWidth() == 16777215,
              f"max={viewer.list.maximumWidth()}")

        # --- расширение панели мышью (двигаем разделитель) ---
        viewer.load_folder(tmp)
        pump(app, 700)
        q_narrow = len(viewer._thumb_queued)
        w_narrow = viewer.list.width()
        viewer.splitter.setSizes([230, 900, 400])
        viewer._on_splitter_moved()   # как при реальном перетаскивании разделителя
        pump(app, 300)
        w_wide = viewer.list.width()
        check("панель реально расширилась", w_wide > w_narrow,
              f"{w_narrow} → {w_wide} px")
        viewer._queue_visible_thumbs()
        q_wide = len(viewer._thumb_queued)
        check("при широкой панели ленивая загрузка ставит больше задач (несколько колонок)",
              q_wide > q_narrow, f"очередь {q_narrow} → {q_wide}")

        # --- ширина запомнилась и восстановилась в новом экземпляре ---
        viewer2 = lv.LocalViewer()
        viewer2.resize(1200, 800)
        viewer2.show()
        pump(app, 300)
        check("в новом запуске ширина восстановлена из настроек",
              viewer2.list.width() > w_narrow + 50,
              f"ширина={viewer2.list.width()} (было {w_narrow})")

        QSettings("ImageHunter", "ImageHunter").remove("viewer/splitter")
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
