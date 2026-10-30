"""Оффлайн-тест поиска по имени и модуля обновлений.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_search.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import __version__  # noqa: E402
from app.core import updates  # noqa: E402
from app.ui.local_viewer import LocalViewer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_image(path: str, color: int = 0x336699) -> None:
    img = QImage(24, 24, QImage.Format.Format_RGB32)
    img.fill(color)
    assert img.save(path)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="ih_search_")
    sub = os.path.join(tmp, "sub")
    deep = os.path.join(sub, "deep")
    hid = os.path.join(tmp, ".hidden")
    for d in (sub, deep, hid):
        os.makedirs(d, exist_ok=True)
    make_image(os.path.join(tmp, "img_a1.png"))
    make_image(os.path.join(tmp, "img_a2.png"))
    make_image(os.path.join(sub, "img_b1.png"))
    make_image(os.path.join(deep, "img_c1.png"))
    make_image(os.path.join(hid, "img_h.png"))
    with open(os.path.join(tmp, "note.txt"), "w") as f:
        f.write("не картинка")

    viewer = LocalViewer()
    viewer.load_folder(tmp)   # задаёт текущую папку

    def wait_until(cond, timeout_s: float = 10.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            app.processEvents()
            if cond():
                time.sleep(0.08)   # хвост: дать прийти завершающему сигналу
                app.processEvents()
                return True
            time.sleep(0.02)
        return False

    try:
        # 1. поиск по подстроке: текущая папка + все подпапки
        viewer.search_edit.setText("img_")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer.list.count() == 4)
        check("поиск «img_» нашёл 4 картинки во вложенных папках", ok,
              f"count={viewer.list.count()}")
        names = {viewer.list.item(i).text() for i in range(viewer.list.count())} \
            if viewer.list.count() else set()
        check("скрытые и не-картинки не попали",
              bool(names) and "img_h.png" not in names and "note.txt" not in names)
        check("результаты из подпапок", bool(names) and "img_b1.png" in names
              and "img_c1.png" in names)

        # 2. регистр не важен (без wildcard)
        viewer.search_edit.setText("IMG_")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer.list.count() == 4)
        check("поиск «IMG_» без учёта регистра", ok, f"count={viewer.list.count()}")

        # 3. уточнение запроса
        viewer.search_edit.setText("b1")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer.list.count() == 1)
        check("поиск «b1» — ровно 1 файл",
              ok and viewer.list.count() == 1 and viewer.list.item(0).text() == "img_b1.png")

        # 4. очистка поля возвращает обычный просмотр текущей папки
        viewer.search_edit.clear()
        ok = wait_until(lambda: viewer.list.count() == 2)
        check("очистка поиска вернула текущую папку (2 файла)", ok,
              f"count={viewer.list.count()}")

        # 5. модуль обновлений
        check("is_newer: заведомо новая версия распознаётся", updates.is_newer("99.0.0", __version__))
        check("is_newer: та же версия не новее", not updates.is_newer(__version__, __version__))
        check("is_newer: 0.10.0 > 0.9.9", updates.is_newer("0.10.0", "0.9.9"))
        check("is_newer: 0.2.10 > 0.2.9", updates.is_newer("0.2.10", "0.2.9"))
        check("установщик найден рядом с приложением", bool(updates.installer_path()),
              updates.installer_path())
        check("RAW_URL указывает на репозиторий",
              updates.RAW_URL.startswith("https://raw.githubusercontent.com/teliy/image-hunter/"))
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
