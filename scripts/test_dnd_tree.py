"""Оффлайн-тест перетаскивания выделенных файлов в папки дерева (v0.8.5).

Проверяет:
1. дерево «Диски и папки» — это _FolderTree: drop'ы принимает, чужие узлы
   в модель не вставляет (DropOnly), сигнал filesDropped связан с вьюером;
2. драг ленты несёт маркер «свой» (application/x-imagehunter-files) —
   по нему дерево узнаёт перетаскивание из программы;
3. наведение на папку дерева: драг принят, папка подсвечена; уход мыши
   (dragLeave) подсветку и таймер раскрытия снимает;
4. наведение на пустое место и заглушку без пути — драг не принят;
5. наведение на свёрнутую папку раскрывает её через задержку
   (ленивое чтение подпапок через expand_hook);
6. отпуск над папкой — файлы ПЕРЕМЕЩЕНЫ (исходник пропал, файл у цели,
   лента перечитана), статус и журнал рассказывают о переносе;
7. отпуск с Ctrl — файлы СКОПИРОВАНЫ (исходник остался);
8. имя занято — файл сохранён как «имя-1.ext», о замене пишет журнал;
9. файлы, уже лежащие в папке-цели, повторно не переносятся («уже в этой
   папке»), несуществующие пути в MIME молча пропускаются;
10. отпуск в ОТКРЫТУЮ папку — лента перечитывается, новые плитки видны;
11. смоук: версия 0.8.5.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_dnd_tree.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QMimeData, QPoint, QSettings, Qt,
)
from PySide6.QtGui import (  # noqa: E402
    QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage,
)
from PySide6.QtWidgets import QApplication, QTreeWidget  # noqa: E402

from app.core import applog, i18n  # noqa: E402
from app.ui.local_viewer import (  # noqa: E402
    _FolderTree, _IH_MIME, LocalViewer, make_file_urls_mime,
)

FAILURES: list[str] = []

# события драка не владеют MIME с точки зрения PySide — держим ссылки
# до конца прогона, иначе GC удалит C++-объект под живым событием
_KEEP_MIME: list = []


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


def wait_until(cond, timeout_s: float = 10.0) -> bool:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


class FakeDrag:
    """Подмена QDrag: запоминает mime и возвращает управление сразу."""

    instances: list["FakeDrag"] = []

    def __init__(self, parent=None):
        self.parent = parent
        self.mime = None
        FakeDrag.instances.append(self)

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pix):
        pass

    def exec(self, *args):
        return Qt.DropAction.CopyAction


def make_image(path: str) -> None:
    img = QImage(48, 36, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    assert img.save(path), f"не удалось сохранить {path}"


def find_item(tree, path: str):
    """Узел дерева по пути из UserRole (вглубь, сравнение как в Проводнике)."""
    want = os.path.normcase(os.path.normpath(path))

    def scan(item):
        for i in range(item.childCount()):
            ch = item.child(i)
            got = ch.data(0, Qt.ItemDataRole.UserRole) or ""
            if got and os.path.normcase(os.path.normpath(got)) == want:
                return ch
            found = scan(ch)
            if found is not None:
                return found
        return None

    return scan(tree.invisibleRootItem())


def file_mime(paths: list[str]) -> QMimeData:
    """MIME как у драга ленты: uri-list + маркер «свой»."""
    mime = make_file_urls_mime(paths)
    mime.setData(_IH_MIME, b"1")
    _KEEP_MIME.append(mime)
    return mime


def send_drag(app, tree, ev_cls, pos: QPoint, mime, ctrl: bool = False):
    """Доставить событие драка во вьюпорт дерева.

    QAbstractScrollArea пропускает DragMove/Drop к item-view только после
    DragEnter — как и в настоящем перетаскивании, поэтому enter шлём всегда
    (свой экземпляр MIME: два события на один объект — гонка владения)."""
    vp = tree.viewport()
    enter_mime = file_mime([])
    enter_mime.setUrls(mime.urls())
    app.sendEvent(vp, make_drag_ev(QDragEnterEvent, pos, enter_mime, ctrl))
    ev = make_drag_ev(ev_cls, pos, mime, ctrl)
    app.sendEvent(vp, ev)
    return ev


def make_drag_ev(ev_cls, pos: QPoint, mime, ctrl: bool = False):
    """Событие драка с заданным MIME."""
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    mods = (Qt.KeyboardModifier.ControlModifier if ctrl
            else Qt.KeyboardModifier.NoModifier)
    return ev_cls(QPoint(pos), actions, mime,
                  Qt.MouseButton.LeftButton, mods)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    applog.setup()

    # собираем строки журнала — по ним проверяем диагностику переноса
    log_lines: list[str] = []
    applog.bridge.record.connect(lambda lvl, line: log_lines.append(line))

    tmp = tempfile.mkdtemp(prefix="ih_dnd_tree_")
    dst = os.path.join(tmp, "dst")
    other = os.path.join(tmp, "other")
    os.makedirs(dst)
    os.makedirs(other)
    for name in ("pic_0.png", "pic_1.png", "pic_2.png", "pic_3.png"):
        make_image(os.path.join(tmp, name))
    make_image(os.path.join(other, "a.png"))
    make_image(os.path.join(other, "b.png"))

    drops: list[tuple] = []
    viewer = None
    try:
        viewer = LocalViewer()
        viewer.resize(1400, 900)
        viewer.show()
        viewer.tree.filesDropped.connect(
            lambda paths, folder, copy: drops.append((list(paths), folder, copy)))
        # tmp — в избранном: узел окажется в дереве с путём в UserRole
        viewer.fav_add(tmp)
        pump(app, 200)
        fav = find_item(viewer.tree, tmp)
        check("папка временного каталога появилась в дереве", fav is not None)
        viewer._populate_children_sync(fav)   # дети (dst, other) — сразу
        dstit = find_item(viewer.tree, dst)
        check("подпапка dst видна в дереве", dstit is not None)
        tree = viewer.tree

        viewer.load_folder(tmp)
        check("лента открыта: 4 файла",
              wait_until(lambda: viewer.list.count() == 4), str(viewer.list.count()))

        # 1. класс и режимы дерева
        check("дерево — _FolderTree", isinstance(tree, _FolderTree))
        check("drop'ы включены (acceptDrops)", tree.acceptDrops())
        check("чужие узлы в модель не вставляются (DropOnly)",
              tree.dragDropMode() == QTreeWidget.DragDropMode.DropOnly)
        check("expand_hook указывает на ленивое чтение подпапок",
              tree.expand_hook == viewer._populate_children)

        # 2. драг ленты несёт маркер «свой»
        viewer.list.clearSelection()
        viewer.list.item(0).setSelected(True)
        viewer.list.item(1).setSelected(True)
        lst = viewer.list
        lst.DRAG_FACTORY = FakeDrag
        FakeDrag.instances.clear()
        lst.exec_drag()
        check("перетаскивание запустилось", len(FakeDrag.instances) == 1)
        if FakeDrag.instances:
            check("в MIME есть маркер «свой» драг",
                  FakeDrag.instances[0].mime.hasFormat(_IH_MIME), _IH_MIME)

        tree.scrollToItem(dstit)
        pump(app, 100)
        dst_pos = tree.visualItemRect(dstit).center()

        # 3. наведение на папку — драг принят, папка подсвечена; уход снимает
        ev = send_drag(app, tree, QDragEnterEvent, dst_pos,
                       file_mime([os.path.join(tmp, "pic_0.png")]))
        check("dragEnter над папкой принят", ev.isAccepted())
        check("папка подсвечена как цель",
              tree._drop_item is dstit
              and dstit.background(0).color() == _FolderTree.HIGHLIGHT)
        ev2 = send_drag(app, tree, QDragMoveEvent, dst_pos,
                        file_mime([os.path.join(tmp, "pic_1.png")]))
        check("dragMove над папкой принят", ev2.isAccepted()
              and tree._drop_item is dstit)
        app.sendEvent(tree.viewport(), QDragLeaveEvent())
        check("уход мыши снял подсветку и таймер",
              tree._drop_item is None and tree._expand_item is None
              and not tree._expand_timer.isActive())

        # 4. пустое место и заглушка драг не принимают
        empty = QPoint(tree.viewport().width() - 5, tree.viewport().height() - 5)
        check("выбрана точка пустого места", tree.itemAt(empty) is None)
        ev3 = send_drag(app, tree, QDragMoveEvent, empty,
                        file_mime([os.path.join(tmp, "pic_0.png")]))
        check("пустое место драг не принимает",
              not ev3.isAccepted() and tree._drop_item is None)
        dummy = LocalViewer._dummy_item()
        tree.addTopLevelItem(dummy)
        pump(app, 100)
        dpos = tree.visualItemRect(dummy).center()
        ev4 = send_drag(app, tree, QDragMoveEvent, dpos,
                        file_mime([os.path.join(tmp, "pic_0.png")]))
        check("заглушка без пути драг не принимает",
              not ev4.isAccepted() and tree._drop_item is None)
        tree.takeTopLevelItem(tree.indexOfTopLevelItem(dummy))
        pump(app, 100)

        # 5. наведение на свёрнутую папку раскрывает её через задержку
        check("dst перед наведением свёрнута", not dstit.isExpanded())
        send_drag(app, tree, QDragMoveEvent, dst_pos,
                  file_mime([os.path.join(tmp, "pic_0.png")]))
        check("таймер раскрытия запущен", tree._expand_timer.isActive())
        os.makedirs(os.path.join(dst, "nested"), exist_ok=True)
        pump(app, int(_FolderTree.AUTO_EXPAND_MS * 1.6) + 250)
        check("папка раскрылась под курсором", dstit.isExpanded())
        check("подпапки дочитаны ленивым загрузчиком",
              wait_until(lambda: viewer._children_loaded(dstit)))
        app.sendEvent(tree.viewport(), QDragLeaveEvent())

        # 6. отпуск над папкой — файлы перенесены
        log_lines.clear()
        drops.clear()
        src0 = os.path.join(tmp, "pic_0.png")
        src1 = os.path.join(tmp, "pic_1.png")
        ev = send_drag(app, tree, QDropEvent, dst_pos, file_mime([src0, src1]))
        check("drop принят", ev.isAccepted())
        check("сигнал filesDropped: пути, папка, без Ctrl",
              drops == [([src0, src1], dst, False)], str(drops))
        check("файлы переехали в dst",
              wait_until(lambda: not os.path.exists(src0)
                         and not os.path.exists(src1)
                         and os.path.isfile(os.path.join(dst, "pic_0.png"))
                         and os.path.isfile(os.path.join(dst, "pic_1.png"))))
        check("лента потеряла уехавшие плитки",
              wait_until(lambda: viewer.list.count() == 2), str(viewer.list.count()))
        check("в статусе итог переноса",
              "dst" in viewer.status.text() and "2" in viewer.status.text(),
              viewer.status.text())
        joined = "\n".join(log_lines)
        check("в журнале начало переноса",
              any("Перемещение: 2 файлов" in ln and "dst" in ln
                  for ln in log_lines), joined[-300:])
        check("в журнале завершение переноса",
              any("успешно 2" in ln for ln in log_lines), joined[-300:])

        # 7. отпуск с Ctrl — копирование
        log_lines.clear()
        src2 = os.path.join(tmp, "pic_2.png")
        send_drag(app, tree, QDropEvent, dst_pos, file_mime([src2]), ctrl=True)
        check("копия доехала в dst",
              wait_until(lambda: os.path.isfile(os.path.join(dst, "pic_2.png"))))
        check("исходник при копировании остался", os.path.isfile(src2))
        check("лента не потеряла плитку (копия)", viewer.list.count() == 2,
              str(viewer.list.count()))

        # 8. имя занято — сохраняется как «имя-1.ext», журнал пишет о замене
        log_lines.clear()
        send_drag(app, tree, QDropEvent, dst_pos, file_mime([src2]), ctrl=True)
        check("второй файл не затёр первый",
              wait_until(lambda: os.path.isfile(os.path.join(dst, "pic_2-1.png")))
              and os.path.isfile(os.path.join(dst, "pic_2.png")))
        # файл мог появиться на диске раньше, чем сигнал done доехал до GUI —
        # ждём именно запись журнала о замене имени
        check("о замене имени пишет журнал",
              wait_until(lambda: any("pic_2.png" in ln and "pic_2-1.png" in ln
                                     for ln in log_lines)),
              "\n".join(log_lines)[-300:])

        # 9. «уже в этой папке» и несуществующие пути
        log_lines.clear()
        send_drag(app, tree, QDropEvent, dst_pos,
                  file_mime([os.path.join(dst, "pic_2.png")]), ctrl=True)
        check("файлы из папки-цели повторно не переносятся",
              "уже в этой папке" in viewer.status.text(), viewer.status.text())
        check("перенос в ту же папку не писал событий журнала",
              not any("Перемещение:" in ln for ln in log_lines),
              "\n".join(log_lines)[-200:])
        ghost = os.path.join(tmp, "ghost.png")
        send_drag(app, tree, QDropEvent, dst_pos, file_mime([ghost]))
        check("несуществующий файл в MIME молча пропущен",
              not os.path.exists(ghost)
              and not any("ghost" in ln for ln in log_lines))

        # 10. отпуск в ОТКРЫТУЮ папку — лента перечитывается
        log_lines.clear()
        fav_pos = tree.visualItemRect(find_item(viewer.tree, tmp)).center()
        send_drag(app, tree, QDropEvent, fav_pos, file_mime(
            [os.path.join(other, "a.png"), os.path.join(other, "b.png")]))
        check("файлы доехали в открытую папку",
              wait_until(lambda: os.path.isfile(os.path.join(tmp, "a.png"))
                         and os.path.isfile(os.path.join(tmp, "b.png"))))
        check("лента перечиталась: 2 старых + 2 новых",
              wait_until(lambda: viewer.list.count() == 4),
              str(viewer.list.count()))
        check("новые плитки в ленте",
              wait_until(lambda: viewer._item_by_path(
                  os.path.join(tmp, "a.png")) is not None))

        # 11. смоук: версия
        from app import __version__
        check("версия 0.8.5", __version__ == "0.8.5", __version__)
    finally:
        try:
            if viewer is not None:
                viewer.fav_remove(tmp)   # не оставлять мусор в настройках
        except Exception:                # noqa: BLE001 — тест мог упасть раньше
            pass
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
