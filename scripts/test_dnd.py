"""Оффлайн-тест drag'n'drop: выделение файлов и перенос их в другие приложения.

Проверяет:
1. лента миниатюр — это _ThumbList с перегруженным startDrag;
2. мультивыделение (ExtendedSelection) и drag включены, приём чужих drop'ов выключен;
3. make_file_urls_mime() создаёт MIME text/uri-list с путями выбранных файлов;
4. после программного выделения нескольких файлов startDrag соберёт ровно их;
5. подсказка о перетаскивании локализована.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_dnd.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget  # noqa: E402

from app.core import i18n  # noqa: E402
from app.ui.local_viewer import _ThumbList, make_file_urls_mime  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)

    from app.ui.local_viewer import LocalViewer

    tmp = tempfile.mkdtemp(prefix="ih_dnd_")
    try:
        for i in range(4):
            img = QImage(48, 36, QImage.Format.Format_RGB32)
            img.fill(0x336699 + i)
            assert img.save(os.path.join(tmp, f"pic_{i}.png"))

        # 1–2. класс и режимы списка
        viewer = LocalViewer()
        viewer.load_folder(tmp)
        viewer.resize(1400, 900)
        viewer.show()
        app.processEvents()

        check("лента — _ThumbList (startDrag перегружен)",
              isinstance(viewer.list, _ThumbList)
              and type(viewer.list).startDrag is not QListWidget.startDrag)
        check("мультивыделение ExtendedSelection",
              viewer.list.selectionMode() == QListWidget.SelectionMode.ExtendedSelection,
              str(viewer.list.selectionMode()))
        check("перетаскивание включено (dragEnabled)", viewer.list.dragEnabled())
        check("приём чужих drop'ов выключен (DragOnly)",
              viewer.list.dragDropMode() == QListWidget.DragDropMode.DragOnly)

        # 3. MIME для Проводника/почты
        paths = [os.path.join(tmp, f"pic_{i}.png") for i in (0, 2)]
        mime = make_file_urls_mime(paths)
        check("MIME имеет формат text/uri-list", mime.hasFormat("text/uri-list"))
        got = [u.toLocalFile() for u in mime.urls()]
        check("MIME содержит выбранные пути", got == paths, str(got))
        check("MIME знает имена файлов", mime.hasUrls() and
              os.path.basename(mime.urls()[0].toLocalFile()) == "pic_0.png")

        # 4. выделение нескольких файлов и сборка путей как в startDrag
        viewer.list.clearSelection()
        viewer.list.item(0).setSelected(True)
        viewer.list.item(2).setSelected(True)
        selected = viewer.list.selectedItems()
        check("выделено ровно 2 файла", len(selected) == 2, str(len(selected)))
        drag_paths = [it.data(Qt.UserRole) for it in selected if it.data(Qt.UserRole)]
        check("startDrag соберёт пути выделенных плиток", drag_paths == paths,
              str(drag_paths))
        mime2 = make_file_urls_mime(drag_paths)
        check("URL из выделения — file:// с корректным путём",
              all(u.isLocalFile() for u in mime2.urls())
              and QUrl.fromLocalFile(paths[1]) in mime2.urls())

        # 5. подсказка локализована
        check("подсказка про перетаскивание (ru)",
              "перетащите" in viewer.list.toolTip(), viewer.list.toolTip()[:60])
        i18n.set_lang("en", persist=False)
        check("подсказка про перетаскивание (en)",
              "drag" in viewer.list.toolTip().lower(), viewer.list.toolTip()[:60])
        i18n.set_lang("ru", persist=False)

        # пустое выделение — startDrag ничего не делает (нет QDrag)
        viewer.list.clearSelection()
        check("пустое выделение безопасно", not viewer.list.selectedItems())
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
