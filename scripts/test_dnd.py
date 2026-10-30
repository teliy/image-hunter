"""Оффлайн-тест drag'n'drop: выделение файлов и перенос их в другие приложения.

Проверяет:
1. лента миниатюр — это _ThumbList с перегруженными startDrag и mouse-событиями;
2. мультивыделение (ExtendedSelection), drag включён, приём чужих drop'ов выключен;
3. make_file_urls_mime() создаёт MIME text/uri-list с путями выбранных файлов;
4. после программного выделения нескольких файлов exec_drag соберёт ровно их;
5. зажали плитку и потянули мышь — перетаскивание стартует (ручной запуск,
   не полагающийся на встроенную механику QListWidget);
6. короткое движение, нажатие на пустое место и «нажал-отпустил» не тянут файлы;
7. подсказка о перетаскивании локализована.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_dnd.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget  # noqa: E402

from app.core import i18n  # noqa: E402
from app.ui.local_viewer import _ThumbList, make_file_urls_mime  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def pump(app, ms: int = 300) -> None:
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


class FakeDrag:
    """Подмена QDrag: запоминает mime/пиктограмму и возвращает управление сразу."""

    instances: list["FakeDrag"] = []

    def __init__(self, parent=None):
        self.parent = parent
        self.mime = None
        self.pixmap = None
        FakeDrag.instances.append(self)

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pix):
        self.pixmap = pix

    def exec(self, *args):
        return Qt.DropAction.CopyAction


def send_mouse(w, ev_type, local: QPoint, button, buttons) -> None:
    g = w.mapToGlobal(local)
    ev = QMouseEvent(ev_type, QPointF(local), QPointF(g), button, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w, ev)


def press_and_move(lst, item, dx: int, select_first: bool = False):
    """Нажать на плитку item и сместить мышь на dx px вправо.

    События шлются в viewport списка — именно туда Qt доставляет мышь
    у item-view; visualItemRect возвращает viewport-относительные координаты.
    """
    vp = lst.viewport()
    c = lst.visualItemRect(item).center()
    send_mouse(vp, QEvent.Type.MouseButtonPress, c,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    for step in (dx // 3, 2 * dx // 3, dx):
        send_mouse(vp, QEvent.Type.MouseMove, c + QPoint(step, 0),
                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    send_mouse(vp, QEvent.Type.MouseButtonRelease, c + QPoint(dx, 0),
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    if select_first:
        item.setSelected(True)


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
        pump(app, 400)
        lst = viewer.list
        lst.DRAG_FACTORY = FakeDrag   # ловим перетаскивание вместо реального QDrag

        check("лента — _ThumbList (startDrag перегружен)",
              isinstance(lst, _ThumbList)
              and type(lst).startDrag is not QListWidget.startDrag)
        check("мышиные события перегружены (ручной запуск)",
              type(lst).mouseMoveEvent is not QListWidget.mouseMoveEvent
              and type(lst).mousePressEvent is not QListWidget.mousePressEvent)
        check("мультивыделение ExtendedSelection",
              lst.selectionMode() == QListWidget.SelectionMode.ExtendedSelection,
              str(lst.selectionMode()))
        check("перетаскивание включено (dragEnabled)", lst.dragEnabled())
        check("приём чужих drop'ов выключен (DragOnly)",
              lst.dragDropMode() == QListWidget.DragDropMode.DragOnly)

        # 3. MIME для Проводника/почты
        paths = [os.path.join(tmp, f"pic_{i}.png") for i in (0, 2)]
        mime = make_file_urls_mime(paths)
        check("MIME имеет формат text/uri-list", mime.hasFormat("text/uri-list"))
        got = [u.toLocalFile() for u in mime.urls()]
        check("MIME содержит выбранные пути", got == paths, str(got))
        check("MIME знает имена файлов", mime.hasUrls() and
              os.path.basename(mime.urls()[0].toLocalFile()) == "pic_0.png")

        # 4. выделение нескольких файлов и сборка путей как в exec_drag
        lst.clearSelection()
        lst.item(0).setSelected(True)
        lst.item(2).setSelected(True)
        selected = lst.selectedItems()
        check("выделено ровно 2 файла", len(selected) == 2, str(len(selected)))
        drag_paths = [it.data(Qt.UserRole) for it in selected if it.data(Qt.UserRole)]
        check("exec_drag соберёт пути выделенных плиток", drag_paths == paths,
              str(drag_paths))
        mime2 = make_file_urls_mime(drag_paths)
        check("URL из выделения — file:// с корректным путём",
              all(u.isLocalFile() for u in mime2.urls())
              and QUrl.fromLocalFile(paths[1]) in mime2.urls())

        # 5. зажали плитку (в выделении 2 файла) и потянули — перетаскивание стартует
        FakeDrag.instances.clear()
        press_and_move(lst, lst.item(0), 40)
        check("потянул плитку — перетаскивание стартовало",
              len(FakeDrag.instances) == 1, str(len(FakeDrag.instances)))
        if FakeDrag.instances:
            d = FakeDrag.instances[0]
            urls = [u.toLocalFile() for u in d.mime.urls()]
            check("потянули — полетели оба выделенных файла", urls == paths,
                  str(urls))
            check("запасной формат text/plain тоже заполнен",
                  d.mime.hasFormat("text/plain")
                  and d.mime.text().splitlines() == paths)
            check("действие — CopyAction", d.mime is not None)

        # 5а. зажали НЕвыделенную плитку и потянули — тащит её одну
        FakeDrag.instances.clear()
        lst.clearSelection()
        pump(app, 100)
        press_and_move(lst, lst.item(3), 40)
        check("нажал на невыделенную плитку и потянул — тащит её одну",
              len(FakeDrag.instances) == 1
              and [u.toLocalFile() for u in FakeDrag.instances[0].mime.urls()]
              == [os.path.join(tmp, "pic_3.png")],
              str([u.toLocalFile() for u in FakeDrag.instances[-1].mime.urls()]
                  if FakeDrag.instances else []))

        # 6. случаи, когда перетаскивания быть не должно
        FakeDrag.instances.clear()
        lst.clearSelection()
        lst.item(1).setSelected(True)
        pump(app, 100)
        press_and_move(lst, lst.item(1), 6)   # меньше порога
        check("короткое движение (меньше порога) не тянет файлы",
              len(FakeDrag.instances) == 0, str(len(FakeDrag.instances)))

        FakeDrag.instances.clear()
        empty = QPoint(lst.viewport().width() - 10, lst.viewport().height() - 10)
        check("выбрана точка пустого места", not lst.indexAt(empty).isValid())
        send_mouse(lst.viewport(), QEvent.Type.MouseButtonPress, empty,
                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        send_mouse(lst.viewport(), QEvent.Type.MouseMove, empty + QPoint(60, 60),
                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        send_mouse(lst.viewport(), QEvent.Type.MouseButtonRelease,
                   empty + QPoint(60, 60),
                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        check("нажатие на пустом месте не тянет файлы",
              len(FakeDrag.instances) == 0, str(len(FakeDrag.instances)))

        FakeDrag.instances.clear()
        c1 = lst.visualItemRect(lst.item(1)).center()
        send_mouse(lst.viewport(), QEvent.Type.MouseButtonPress, c1,
                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        send_mouse(lst.viewport(), QEvent.Type.MouseButtonRelease, c1,
                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        send_mouse(lst.viewport(), QEvent.Type.MouseMove, c1 + QPoint(60, 0),
                   Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
        check("нажал-отпустил (клик) — перетаскивания нет",
              len(FakeDrag.instances) == 0, str(len(FakeDrag.instances)))

        # прямые вызовы запасного пути
        FakeDrag.instances.clear()
        lst.clearSelection()
        lst.exec_drag()
        check("пустое выделение безопасно", len(FakeDrag.instances) == 0)
        lst.item(1).setSelected(True)
        lst.startDrag(Qt.DropAction.CopyAction)
        check("startDrag (запасной путь) тоже работает",
              len(FakeDrag.instances) == 1
              and [u.toLocalFile() for u in FakeDrag.instances[0].mime.urls()]
              == [os.path.join(tmp, "pic_1.png")])

        # 7. подсказка локализована
        check("подсказка про перетаскивание (ru)",
              "перетащите" in lst.toolTip(), lst.toolTip()[:60])
        i18n.set_lang("en", persist=False)
        check("подсказка про перетаскивание (en)",
              "drag" in lst.toolTip().lower(), lst.toolTip()[:60])
        i18n.set_lang("ru", persist=False)
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
