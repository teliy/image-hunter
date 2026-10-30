"""Оффлайн-тест удаления (корзина + запасное окончательное) и персиста.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_delete_restore.py
"""

import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QImage, QKeySequence, QShortcut

from app.core import i18n
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(app, cond, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


class FakeSI:
    def __init__(self, path: str):
        self._path = path

    def isValid(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def isReady(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def rootPath(self) -> str:  # noqa: N802 (Qt API)
        return self._path

    def displayName(self) -> str:  # noqa: N802 (Qt API)
        return self._path

    def fileSystemType(self) -> bytes:  # noqa: N802 (Qt API)
        return b"ext4"

    def bytesTotal(self) -> int:  # noqa: N802 (Qt API)
        return 0

    def bytesFree(self) -> int:  # noqa: N802 (Qt API)
        return 0


class FakeQFile:
    """Подмена QFile.moveToTrash: записи не удаляются, всё журналируется."""

    trashed: list[str] = []
    fail_names: set[str] = set()   # имена файлов, для которых «корзина» откажет

    @staticmethod
    def moveToTrash(path: str):
        name = os.path.basename(path)
        if name in FakeQFile.fail_names:
            return False, ""
        FakeQFile.trashed.append(path)
        return True, os.path.join("/fake/trash", name)


class Answers:
    """Подмена QMessageBox.question: последовательность ответов + titles."""

    def __init__(self, *vals):
        self.vals = list(vals)
        self.titles: list[str] = []

    def __call__(self, *a, **k):
        self.titles.append(a[1] if len(a) > 1 else "")
        return (self.vals.pop(0) if self.vals
                else lv.QMessageBox.StandardButton.No)


def make_png(path: str) -> None:
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(0xFF00FF00)
    assert img.save(path)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ih_del_")
    names = ("a.png", "b.png", "c.png", "d.png")

    def fresh() -> None:
        for name in names:
            p = os.path.join(tmp, name)
            if not os.path.exists(p):
                make_png(p)

    class _Loc:
        HomeLocation = 0
        PicturesLocation = 1
        GenericCacheLocation = 2

    class FakeStdPaths:
        StandardLocation = _Loc

        @staticmethod
        def writableLocation(_kind) -> str:
            return tempfile.mkdtemp(prefix="ih_home_")

    lv.QStandardPaths = FakeStdPaths
    lv.QStorageInfo = types.SimpleNamespace(mountedVolumes=lambda: [FakeSI(tmp)])

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    i18n.set_lang("ru", persist=False)

    viewer = LocalViewer()
    viewer.resize(900, 700)
    viewer.show()
    app.processEvents()

    lv.QFile = FakeQFile

    # ---------- 1. удаление в корзину: подтверждение «Да» ----------
    fresh()
    viewer.load_folder(tmp)
    app.processEvents()
    check("папка загружена (4 файла)", viewer.list.count() == 4)
    viewer.list.item(0).setSelected(True)   # a.png
    viewer.list.item(2).setSelected(True)   # c.png

    FakeQFile.trashed.clear()
    FakeQFile.fail_names.clear()
    ans = Answers(lv.QMessageBox.StandardButton.Yes)
    lv.QMessageBox.question = staticmethod(ans)

    viewer.delete_selected_files()
    app.processEvents()
    check("в корзину ушло 2 файла", len(FakeQFile.trashed) == 2,
          str(FakeQFile.trashed))
    check("задан ровно один диалог (обычное подтверждение)",
          ans.titles == [i18n.tr("viewer.del_title")], str(ans.titles))
    check("в списке осталось 2 файла", viewer.list.count() == 2)
    check("статус: Удалено в корзину: 2", "2" in viewer.status.text(),
          viewer.status.text())

    # шорткат Delete действительно висит на списке
    del_seq = QKeySequence(QKeySequence.StandardKey.Delete)
    scs = viewer.list.findChildren(QShortcut)
    check("шорткат Delete на списке есть",
          any(sc.key().matches(del_seq) == QKeySequence.SequenceMatch.ExactMatch
              for sc in scs), str([sc.key().toString() for sc in scs]))

    # ---------- 2. корзина отказала + «Да» → удаление окончательно ----------
    fresh()
    viewer.load_folder(tmp)
    app.processEvents()
    FakeQFile.fail_names = {"a.png"}
    ans = Answers(lv.QMessageBox.StandardButton.Yes,   # корзина
                  lv.QMessageBox.StandardButton.Yes)   # окончательно?
    lv.QMessageBox.question = staticmethod(ans)
    viewer.list.item(0).setSelected(True)   # a.png
    viewer.delete_selected_files()
    app.processEvents()
    check("после отказа корзины был второй диалог",
          ans.titles == [i18n.tr("viewer.del_title"),
                         i18n.tr("viewer.del_perm_ask_title")], str(ans.titles))
    check("файл удалён с диска окончательно",
          not os.path.exists(os.path.join(tmp, "a.png")))
    check("в списке осталось 3 файла", viewer.list.count() == 3)
    check("_paths без удалённого файла",
          all(os.path.basename(p) != "a.png" for p in viewer._paths))
    check("статус: Удалено окончательно: 1",
          "окончательно: 1" in viewer.status.text(), viewer.status.text())

    # ---------- 3. корзина отказала + «Нет» → файл остаётся ----------
    fresh()
    viewer.load_folder(tmp)
    app.processEvents()
    ans = Answers(lv.QMessageBox.StandardButton.Yes,   # корзина
                  lv.QMessageBox.StandardButton.No)    # окончательно? — нет
    lv.QMessageBox.question = staticmethod(ans)
    viewer.list.item(0).setSelected(True)   # a.png
    viewer.delete_selected_files()
    app.processEvents()
    check("при отказе обоих путей файл остаётся на диске",
          os.path.exists(os.path.join(tmp, "a.png")))
    check("в списке 4 файла", viewer.list.count() == 4)
    check("статус: удалено 0, не удалось 1",
          "не удалось" in viewer.status.text() and ": 0," in viewer.status.text(),
          viewer.status.text())

    # ---------- 4. диск без корзины: сразу диалог об окончательном ----------
    fresh()
    FakeQFile.trashed.clear()
    real_has_trash = lv._drive_has_trash
    lv._drive_has_trash = lambda p: False     # Z:/сетевой диск без корзины
    try:
        viewer.load_folder(tmp)
        app.processEvents()
        ans = Answers(lv.QMessageBox.StandardButton.Yes)
        lv.QMessageBox.question = staticmethod(ans)
        viewer.list.item(0).setSelected(True)   # a.png
        viewer.delete_selected_files()
        app.processEvents()
        check("на диске без корзины задан один диалог о полном удалении",
              ans.titles == [i18n.tr("viewer.del_perm_title")], str(ans.titles))
        check("файл удалён навсегда (без попытки корзины)",
              not FakeQFile.trashed
              and not os.path.exists(os.path.join(tmp, "a.png")))
        check("в списке 3 файла", viewer.list.count() == 3)
        check("статус: Удалено окончательно: 1",
              "окончательно: 1" in viewer.status.text(), viewer.status.text())
    finally:
        lv._drive_has_trash = real_has_trash

    # ---------- 5. «Нет» в подтверждении: ничего не удаляется ----------
    fresh()
    viewer.load_folder(tmp)
    app.processEvents()
    FakeQFile.trashed.clear()
    ans = Answers(lv.QMessageBox.StandardButton.No)
    lv.QMessageBox.question = staticmethod(ans)
    viewer.list.item(0).setSelected(True)
    viewer.delete_selected_files()
    app.processEvents()
    check("«Нет» — ни один файл не ушёл в корзину", not FakeQFile.trashed)
    check("«Нет» — список не изменился", viewer.list.count() == 4)

    # ---------- 6. удаление последнего файла: просмотр очищается ----------
    viewer.load_folder(tmp)
    app.processEvents()
    FakeQFile.fail_names.clear()
    ans = Answers(lv.QMessageBox.StandardButton.Yes)
    lv.QMessageBox.question = staticmethod(ans)
    viewer.list.selectAll()
    viewer.delete_selected_files()
    app.processEvents()
    check("все файлы удалены — список пуст", viewer.list.count() == 0)
    check("просмотр очищен", viewer.view_label.text() != "",
          viewer.view_label.text())

    # ---------- 7. read-only файл удаляется окончательно ----------
    ro = os.path.join(tmp, "ro.png")
    make_png(ro)
    os.chmod(ro, 0o444)   # «только чтение» — как бывают скачанные webp
    lv._drive_has_trash = lambda p: False
    try:
        viewer.load_folder(tmp)
        app.processEvents()
        ans = Answers(lv.QMessageBox.StandardButton.Yes)
        lv.QMessageBox.question = staticmethod(ans)
        row = next(i for i in range(viewer.list.count())
                   if os.path.basename(viewer.list.item(i).data(Qt.UserRole))
                   == "ro.png")
        viewer.list.item(row).setSelected(True)   # ro.png
        viewer.delete_selected_files()
        app.processEvents()
        check("read-only файл удалён окончательно", not os.path.exists(ro))
    finally:
        lv._drive_has_trash = real_has_trash

    # ---------- 8. восстановление последнего запроса при старте ----------
    fresh()
    st.setValue("viewer/last_folder", tmp)
    st.setValue("viewer/last_query", "b")
    viewer2 = LocalViewer()
    check("запрос подставлен в поле при старте", viewer2.search_edit.text() == "b",
          viewer2.search_edit.text())
    ok = wait_until(app, lambda: viewer2._search_handle is None
                    and viewer2._search_count == 1)
    check("восстановленный запрос сам запустил поиск (1 совпадение)", ok,
          f"count={viewer2._search_count} list={viewer2.list.count()}")
    check("найден b.png", viewer2.list.count() == 1
          and os.path.basename(viewer2.list.item(0).data(Qt.UserRole)) == "b.png")

    # ---------- 9. save_state запоминает папку и запрос ----------
    viewer3 = LocalViewer()
    viewer3.load_folder(tmp)
    viewer3.search_edit.setText("c")     # поиск не ждём — save_state читает поле
    viewer3.save_state()
    st2 = QSettings("ImageHunter", "ImageHunter")
    check("save_state: папка", os.path.normpath(st2.value("viewer/last_folder", ""))
          == os.path.normpath(tmp), st2.value("viewer/last_folder", ""))
    check("save_state: запрос", st2.value("viewer/last_query", "") == "c",
          st2.value("viewer/last_query", ""))

    # ---------- 10. i18n-ключи есть во всех трёх языках ----------
    need = ["viewer.ctx_delete", "viewer.ctx_delete_tip", "viewer.del_title",
            "viewer.del_confirm", "viewer.del_nothing", "viewer.del_done",
            "viewer.del_done_err", "viewer.del_missing", "viewer.del_failed",
            "viewer.del_perm_title", "viewer.del_perm_confirm",
            "viewer.del_perm_ask_title", "viewer.del_perm_ask",
            "viewer.del_done_perm", "viewer.del_done_mixed",
            "log.event.trash", "log.event.trash_err", "log.event.delete_perm"]
    for key in need:
        langs = i18n._STRINGS.get(key, {})
        check(f"i18n {key}: ru/en/zh",
              all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
    # подстановки в новых строках
    check("del_perm_confirm: {n} подставляется",
          "{n}" not in i18n.tr("viewer.del_perm_confirm", n=3))
    check("del_perm_ask: {n} подставляется",
          "{n}" not in i18n.tr("viewer.del_perm_ask", n=2))
    check("del_done_mixed: {n}/{t}/{p} подставляются",
          i18n.tr("viewer.del_done_mixed", n=4, t=3, p=1) ==
          "Удалено: 4 (в корзину 3, окончательно 1)")
    check("log.event.delete_perm: {n}/{folder} подставляются",
          "{n}" not in i18n.tr("log.event.delete_perm", n=2, folder="X")
          and "{folder}" not in i18n.tr("log.event.delete_perm", n=2, folder="X"))

    # уборка: не оставлять тестовые папку/запрос в настройках
    st2.setValue("viewer/last_folder", "")
    st2.setValue("viewer/last_query", "")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt: известные abort'ы при разрушении виджетов в песочнице
