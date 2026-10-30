"""Оффлайн-тест дерева дисков/папок во вкладке «Мои картинки».

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_tree.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage

from app.ui.local_viewer import LocalViewer, list_image_files
from PySide6.QtCore import QSettings

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_test_images(folder: str, names_colors) -> None:
    os.makedirs(folder, exist_ok=True)
    for i, (name, (r, g, b)) in enumerate(names_colors):
        img = QImage(24, 24, QImage.Format.Format_RGB32)
        img.fill(((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF))
        ok = img.save(os.path.join(folder, name))
        assert ok, f"не удалось сохранить {name}"


def main() -> int:
    tmp_root = tempfile.mkdtemp(prefix="ih_tree_")
    sub_a = os.path.join(tmp_root, "Фотки 2024")
    sub_b = os.path.join(tmp_root, "empty_dir")
    make_test_images(tmp_root, [("b.png", (255, 0, 0)), ("a10.jpg", (0, 255, 0))])
    make_test_images(sub_a, [("img1.png", (0, 0, 255)), ("img2.png", (255, 255, 0))])
    os.makedirs(sub_b, exist_ok=True)
    os.makedirs(os.path.join(tmp_root, ".hidden_dir"), exist_ok=True)
    with open(os.path.join(tmp_root, "note.txt"), "w") as f:
        f.write("не картинка")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)  # изолируем тесты
    viewer = LocalViewer()
    viewer.resize(800, 900)
    viewer.show()   # ленивые миниатюры грузятся только для видимых строк

    # 1. дерево построено: есть диски (include_all — песочница на overlay-fs)
    viewer.refresh_drives(include_all=True)
    tops = [viewer.tree.topLevelItem(i) for i in range(viewer.tree.topLevelItemCount())]
    top_paths = [t.data(0, Qt.ItemDataRole.UserRole) for t in tops]
    check("дерево содержит хотя бы один диск", any(p == "/" or (p and p[1:2] == ":") for p in top_paths),
          str(top_paths))

    # 2. быстрые ссылки Домой
    check("быстрая ссылка «Домой» есть", any(p == os.path.expanduser("~") for p in top_paths))

    # 3. ленивое раскрытие корня диска
    root_item = next(t for t in tops if t.data(0, Qt.ItemDataRole.UserRole) in ("/", "C:\\", "C:/"))
    viewer._populate_children(root_item)
    kids = [root_item.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(root_item.childCount())]
    check("корень диска раскрылся и показал подпапки", len(kids) > 0, f"{len(kids)} шт.")
    check("заглушка после раскрытия удалена",
          all(k for k in kids), "нет пустых путей")

    # 4. клик по папке загружает изображения (через _on_tree_clicked)
    target_item = viewer._expand_towards(root_item, os.path.join(tmp_root, "Фотки 2024"))
    check("путь к тестовой папке раскрылся в дереве", target_item is not None)
    if target_item is not None:
        viewer._on_tree_clicked(target_item, 0)
        check("клик по папке загрузил файлы папки", viewer.list.count() == 2,
              f"count={viewer.list.count()}")
        check("сортировка естественная (img1 < img2)",
              [viewer.list.item(i).text() for i in range(2)] == ["img1.png", "img2.png"])
        check("после клика папка отмечена раскрытой", target_item.isExpanded())

    # 5. корень тестовой папки: 2 картинки, txt и скрытая папка не мешают
    viewer.load_folder(tmp_root)
    check("в корне тестовой папки 2 изображения", viewer.list.count() == 2,
          f"count={viewer.list.count()}")

    # 6. пустая папка — сообщение и 0 файлов
    viewer.load_folder(sub_b)
    check("пустая папка — 0 миниатюр", viewer.list.count() == 0)

    # 7. синхронизация дерева по внешнему пути («Открыть папку…»)
    viewer.refresh_drives(include_all=True)
    viewer.load_folder(sub_a, sync_tree=True)
    cur = viewer.tree.currentItem()
    cur_path = cur.data(0, Qt.ItemDataRole.UserRole) if cur else None
    check("синхронизация дерева подсветила папку", cur_path == sub_a, str(cur_path))
    check("путь в дереве раскрыт до папки", bool(cur and cur.parent() is not None and cur.parent().isExpanded()))

    # 8. миниатюры реально отрисовываются (фоновые задачи; счётчик накопительный — берём дельту)
    done_before = viewer._thumbs_done
    viewer.load_folder(sub_a)
    deadline = 0
    while viewer._thumbs_done < done_before + 2 and deadline < 200:
        app.processEvents()
        time.sleep(0.02)  # реальная пауза: таймер пачки миниатюр срабатывает раз в 120 мс
        app.processEvents()
        deadline += 1
    check("миниатюры отрисованы", viewer._thumbs_done >= done_before + 2,
          f"done={viewer._thumbs_done} (было {done_before})")

    # 9. list_image_files не сломан
    check("list_image_files возвращает 2 файла", len(list_image_files(tmp_root)) == 2)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt: известные abort'ы при разрушении виджетов в песочнице
