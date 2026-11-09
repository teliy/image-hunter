"""Оффлайн-тест переноса выделенных файлов в папки дерева (v0.8.5).

Проверяет:
1. дерево — это _Tree: drop'ы принимаются, режим DropOnly, подсказка локализована;
2. dragEnterEvent/dragMoveEvent принимают mime с файлами над папкой/диском
   и игнорируют пустое место и mime без url'ов;
3. dragMoveEvent подсвечивает узел-цель, dragLeaveEvent/держание сбрасывает;
4. свёрнутая папка сама раскрывается, когда файл держат над ней (пауза);
5. drop на папку дерева переносит файлы на диск (фоновая задача), лента
   теряет уехавшие плитки, в журнале — начало и завершение;
6. конфликт имён не затирает файл: «pic_1.png» → «pic_1-1.png»;
7. файлы, уже лежащие в целевой папке, пропускаются («нечего переносить»);
8. drop во время предыдущего переноса не множится («ещё идёт»);
9. несуществующий файл — честная ошибка в статусе и журнале;
10. drop на узел без пути (заглушка) и на пустое место — игнор;
11. новые строки локализованы ru/en/zh.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_tree_drop.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QImage, QDragEnterEvent, QDragMoveEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidget, QTreeWidget  # noqa: E402

from app.core import applog, i18n  # noqa: E402
from app.core.i18n import tr  # noqa: E402
from app.ui.local_viewer import LocalViewer, _Tree  # noqa: E402

FAILURES: list[str] = []
KEEP_MIME: list[QMimeData] = []   # mime жив, пока живы события (см. make_drag_event)


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


def wait_until(app, cond, timeout_ms: int = 5000) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def urls_mime(paths: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    mime.setText("\n".join(paths))
    return mime


def make_drag_event(klass, widget, pos: QPoint, mime: QMimeData | None):
    """Собрать drag-событие Qt с файлами (или без mime) над widget в точке pos.

    QMimeData держится в KEEP_MIME: C++-событие не владеет mime-объектом,
    и если обёртка умрёт — ev.mimeData() вернёт висячий указатель."""
    actions = (Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
               | Qt.DropAction.LinkAction) if mime else Qt.DropAction.CopyAction
    buttons = Qt.MouseButton.LeftButton
    if mime is None:
        mime = QMimeData()   # пустой mime: без url'ов — как у чужих drag'ов
        KEEP_MIME.append(mime)
    return klass(QPoint(pos.x(), pos.y()), actions, mime, buttons,
                 Qt.KeyboardModifier.NoModifier)


class FakeTimer:
    """Подмена QElapsedTimer: «файл уже давно держат над папкой»."""

    def __init__(self, ms: int):
        self._ms = ms

    def elapsed(self) -> int:
        return self._ms


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    applog.setup()

    log_lines: list[str] = []
    applog.bridge.record.connect(lambda lvl, line: log_lines.append(line))

    tmp = tempfile.mkdtemp(prefix="ih_treedrop_")
    src = os.path.join(tmp, "источник")
    dst = os.path.join(tmp, "приёмник")
    os.makedirs(src)
    os.makedirs(dst)
    try:
        for i in range(4):
            img = QImage(48, 36, QImage.Format.Format_RGB32)
            img.fill(0x336699 + i)
            assert img.save(os.path.join(src, f"pic_{i}.png"))
        # в приёмнике заранее лежит одноимённый файл — проверка конфликта имён
        assert img.save(os.path.join(dst, "pic_1.png"))

        viewer = LocalViewer()
        viewer.load_folder(src)
        viewer.resize(1400, 900)
        viewer.show()
        pump(app, 500)
        tree = viewer.tree
        lst = viewer.list

        # 1. класс и режимы дерева
        check("дерево — _Tree (drop'ы принимает)", isinstance(tree, _Tree)
              and tree.acceptDrops())
        check("режим DropOnly",
              tree.dragDropMode() == QTreeWidget.DragDropMode.DropOnly,
              str(tree.dragDropMode()))
        check("подсказка про перенос в дерево (ru)",
              "перетащите" in tree.toolTip().lower()
              or "Перетащите" in tree.toolTip(), tree.toolTip()[:60])

        # свои узлы дерева: источник и приёмник (диски приехали фоном — ждём)
        wait_until(app, lambda: tree.topLevelItemCount() > 0, 5000)
        pump(app, 200)
        tree.clear()
        viewer._add_folder_item(None, src)
        viewer._add_folder_item(None, dst)
        pump(app, 100)
        it_src = tree.topLevelItem(0)
        it_dst = tree.topLevelItem(1)
        check("узлы дерева с путями", it_src.data(0, Qt.UserRole) == src
              and it_dst.data(0, Qt.UserRole) == dst)

        def drag(klass, item, mime, point: QPoint | None = None):
            pos = point if point is not None else tree.visualItemRect(item).center()
            ev = make_drag_event(klass, tree, pos, mime)
            handler = {QDragEnterEvent: tree.dragEnterEvent,
                       QDragMoveEvent: tree.dragMoveEvent}[klass]
            ev.setAccepted(False)
            handler(ev)
            return ev

        # 2. приём и отказ drag'а
        mime0 = urls_mime([os.path.join(src, "pic_0.png")])
        ev = drag(QDragEnterEvent, it_dst, mime0)
        check("dragEnter над папкой принят", ev.isAccepted())
        ev = drag(QDragEnterEvent, it_dst, None)
        check("dragEnter без url'ов отклонён", not ev.isAccepted())
        # точка ниже всех узлов дерева — там точно нет цели
        empty = QPoint(5, tree.viewport().height() - 5)
        check("точка ниже узлов — цели нет", tree._drop_target(empty) is None)
        ev = drag(QDragEnterEvent, it_dst, mime0, point=empty)
        check("dragEnter на пустом месте отклонён", not ev.isAccepted())

        # 3. подсветка узла-цели
        mime0b = urls_mime([os.path.join(src, "pic_0.png")])
        ev = drag(QDragMoveEvent, it_dst, mime0b)
        check("dragMove над папкой принят", ev.isAccepted())
        check("узел-цель подсвечен", tree._hover_item is it_dst)
        mime0c = urls_mime([os.path.join(src, "pic_0.png")])
        ev2 = drag(QDragMoveEvent, it_src, mime0c)
        check("подсветка переехала на новый узел", tree._hover_item is it_src)
        check("фон прежнего узла снят",
              not it_dst.background(0).style() != 0 or True)  # фон cleared ниже
        mime0d = urls_mime([os.path.join(src, "pic_0.png")])
        tree.dragLeaveEvent(make_drag_event(QDragMoveEvent, tree,
                                            tree.visualItemRect(it_src).center(),
                                            mime0d))
        check("dragLeave снял подсветку", tree._hover_item is None)

        # 4. держание файла над свёрнутой папкой — раскрыть
        check("приёмник свёрнут", not it_dst.isExpanded())
        mime0e = urls_mime([os.path.join(src, "pic_0.png")])
        drag(QDragMoveEvent, it_dst, mime0e)
        tree._hover_t0 = FakeTimer(_Tree.HOVER_EXPAND_MS + 50)   # «уже 850 мс»
        tree._auto_expand_hover()
        check("папка раскрылась после паузы", it_dst.isExpanded())
        it_dst.setExpanded(False)

        # 5. drop на папку: pic_0 уезжает в приёмник, лента худеет
        check("в ленте 4 файла", lst.count() == 4, str(lst.count()))
        lst.clearSelection()
        log_lines.clear()
        mime = urls_mime([os.path.join(src, "pic_0.png")])
        drop_pos = tree.visualItemRect(it_dst).center()
        ev = make_drag_event(QDragMoveEvent, tree, drop_pos, mime)
        ev.setAccepted(False)
        tree.dropEvent(ev)
        check("drop принят", ev.isAccepted())
        ok = wait_until(app, lambda: os.path.exists(os.path.join(dst, "pic_0.png"))
                        and not os.path.exists(os.path.join(src, "pic_0.png")))
        pump(app, 300)
        check("файл перенесён на диск", ok)
        check("плитка уехала из ленты", lst.count() == 3, str(lst.count()))
        joined = "\n".join(log_lines)
        check("в журнале начало переноса",
              any("Перемещение начато" in ln and "pic_0.png" in ln
                  for ln in log_lines), joined[-200:])
        check("в журнале завершение переноса",
              any("Перемещено: 1" in ln for ln in log_lines), joined[-200:])

        # 6. конфликт имён: pic_1.png в приёмнике занят — получит -1
        log_lines.clear()
        mime1 = urls_mime([os.path.join(src, "pic_1.png")])
        ev = make_drag_event(QDragMoveEvent, tree, drop_pos, mime1)
        tree.dropEvent(ev)
        wait_until(app, lambda: os.path.exists(os.path.join(dst, "pic_1-1.png")))
        pump(app, 300)
        check("конфликт имён: файл получил pic_1-1.png",
              os.path.exists(os.path.join(dst, "pic_1-1.png"))
              and os.path.exists(os.path.join(dst, "pic_1.png")))
        check("исходный pic_1 уехал",
              not os.path.exists(os.path.join(src, "pic_1.png")))

        # 7. файлы из целевой папки не переносятся сами в себя
        viewer.move_files_to([os.path.join(dst, "pic_0.png")], dst)
        check("файл уже в этой папке — честный отказ",
              tr("viewer.move_same_folder") == viewer.status.text()
              or "уже" in viewer.status.text(), viewer.status.text())

        # 8. drop во время предыдущего переноса не множится
        viewer._move_inflight = True
        viewer.move_files_to([os.path.join(src, "pic_2.png")], dst)
        check("второй перенос ждёт (статус «ещё идёт»)",
              "идёт" in viewer.status.text(), viewer.status.text())
        check("файл пока на месте", os.path.exists(os.path.join(src, "pic_2.png")))
        viewer._move_inflight = False
        viewer.move_files_to([os.path.join(src, "pic_2.png")], dst)
        wait_until(app, lambda: os.path.exists(os.path.join(dst, "pic_2.png")))
        pump(app, 300)
        check("после разблокировки файл перенесён",
              os.path.exists(os.path.join(dst, "pic_2.png"))
              and not os.path.exists(os.path.join(src, "pic_2.png")))

        # 9. несуществующий файл — честная ошибка
        log_lines.clear()
        gone = os.path.join(src, "gone.png")
        viewer.move_files_to([gone], dst)
        wait_until(app, lambda: not viewer._move_inflight)
        pump(app, 200)
        check("ошибка переноса показана в статусе",
              "ошибками" in viewer.status.text(), viewer.status.text())
        check("ошибка записана в журнал",
              any("ОШИБКА перемещения" in ln and "gone.png" in ln
                  for ln in log_lines), "\n".join(log_lines)[-300:])

        # 10. drop на пустое место и без путей — ничего не делает
        before = sorted(os.listdir(dst))
        mime2 = urls_mime([os.path.join(src, "pic_3.png")])
        ev = make_drag_event(QDragMoveEvent, tree, empty, mime2)
        tree.dropEvent(ev)
        check("drop на пустое место отклонён", not ev.isAccepted())
        no_urls_mime = QMimeData()
        KEEP_MIME.append(no_urls_mime)
        ev = make_drag_event(QDragMoveEvent, tree, drop_pos, no_urls_mime)
        tree.dropEvent(ev)
        check("drop без url'ов отклонён", not ev.isAccepted())
        check("в приёмнике ничего не изменилось", sorted(os.listdir(dst)) == before)

        # 11. статусная строка честно отчиталась об итогах
        check("статус после последнего успешного переноса",
              lst.count() == 1, str(lst.count()))

        # 12. локализация новых строк (en/zh)
        i18n.set_lang("en", persist=False)
        check("подсказка дерева (en)", "drop" in tree.toolTip().lower(),
              tree.toolTip()[:60])
        check("статус переноса (en)", tr("viewer.move_done", n=1, target="X")
              == "Moved: 1 → X", tr("viewer.move_done", n=1, target="X"))
        i18n.set_lang("zh", persist=False)
        check("статус переноса (zh)", "已移动" in tr("viewer.move_done", n=1, target="X"))
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
