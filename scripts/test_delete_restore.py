"""Оффлайн-тест удаления файлов в корзину и запоминания последнего запроса.

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


def make_png(path: str) -> None:
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(0xFF00FF00)
    assert img.save(path)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ih_del_")
    for name in ("a.png", "b.png", "c.png"):
        make_png(os.path.join(tmp, name))

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

    # ---------- 1. удаление: подтверждение «Да» ----------
    viewer.load_folder(tmp)
    app.processEvents()
    check("папка загружена (3 файла)", viewer.list.count() == 3)
    viewer.list.item(0).setSelected(True)   # a.png
    viewer.list.item(2).setSelected(True)   # c.png

    FakeQFile.trashed.clear()
    FakeQFile.fail_names.clear()
    lv.QFile = FakeQFile
    lv.QMessageBox.question = staticmethod(
        lambda *a, **k: lv.QMessageBox.StandardButton.Yes)

    viewer.delete_selected_files()
    app.processEvents()
    check("в корзину ушло 2 файла", len(FakeQFile.trashed) == 2,
          str(FakeQFile.trashed))
    check("в списке остался 1 файл", viewer.list.count() == 1)
    check("_paths усечён синхронно со списком",
          os.path.basename(viewer._paths[0]) == "b.png", str(viewer._paths))
    check("выделение не потерялось", viewer.list.currentItem() is not None)
    check("статус: Удалено в корзину: 2", "2" in viewer.status.text(),
          viewer.status.text())

    # шорткат Delete действительно висит на списке
    del_seq = QKeySequence(QKeySequence.StandardKey.Delete)
    scs = viewer.list.findChildren(QShortcut)
    check("шорткат Delete на списке есть",
          any(sc.key().matches(del_seq) == QKeySequence.SequenceMatch.ExactMatch
              for sc in scs), str([sc.key().toString() for sc in scs]))

    # ---------- 2. отказ корзины: файл остаётся, ошибка в статусе ----------
    viewer.load_folder(tmp)
    app.processEvents()
    FakeQFile.fail_names = {"a.png"}
    viewer.list.item(0).setSelected(True)
    viewer.delete_selected_files()
    app.processEvents()
    check("при отказе корзины файл остаётся", viewer.list.count() == 3)
    check("статус: удалено 0, не удалось 1",
          "не удалось" in viewer.status.text() and ": 0," in viewer.status.text(),
          viewer.status.text())

    # ---------- 3. «Нет» в подтверждении: ничего не удаляется ----------
    lv.QMessageBox.question = staticmethod(
        lambda *a, **k: lv.QMessageBox.StandardButton.No)
    FakeQFile.trashed.clear()
    viewer.list.item(0).setSelected(True)
    viewer.delete_selected_files()
    app.processEvents()
    check("«Нет» — ни один файл не ушёл в корзину", not FakeQFile.trashed)
    check("«Нет» — список не изменился", viewer.list.count() == 3)

    # ---------- 4. удаление последнего файла: просмотр очищается ----------
    viewer.load_folder(tmp)
    app.processEvents()
    lv.QMessageBox.question = staticmethod(
        lambda *a, **k: lv.QMessageBox.StandardButton.Yes)
    FakeQFile.fail_names.clear()
    viewer.list.selectAll()
    viewer.delete_selected_files()
    app.processEvents()
    check("все файлы удалены — список пуст", viewer.list.count() == 0)
    check("просмотр очищен", viewer.view_label.text() != "",
          viewer.view_label.text())

    # ---------- 5. восстановление последнего запроса при старте ----------
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

    # ---------- 6. save_state запоминает папку и запрос ----------
    viewer3 = LocalViewer()
    viewer3.load_folder(tmp)
    viewer3.search_edit.setText("c")     # поиск не ждём — save_state читает поле
    viewer3.save_state()
    st2 = QSettings("ImageHunter", "ImageHunter")
    check("save_state: папка", os.path.normpath(st2.value("viewer/last_folder", ""))
          == os.path.normpath(tmp), st2.value("viewer/last_folder", ""))
    check("save_state: запрос", st2.value("viewer/last_query", "") == "c",
          st2.value("viewer/last_query", ""))
    check("запрос пишется и при самом поиске",
          st2.value("viewer/last_query", "") == "c")

    # ---------- 7. новые i18n-ключи есть во всех трёх языках ----------
    need = ["viewer.ctx_delete", "viewer.ctx_delete_tip", "viewer.del_title",
            "viewer.del_confirm", "viewer.del_nothing", "viewer.del_done",
            "viewer.del_done_err", "viewer.del_missing", "viewer.del_failed",
            "log.event.trash", "log.event.trash_err"]
    for key in need:
        langs = i18n._STRINGS.get(key, {})
        check(f"i18n {key}: ru/en/zh",
              all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))

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
