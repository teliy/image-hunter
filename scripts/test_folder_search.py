"""Оффлайн-тест поиска папок в дереве «Диски и папки».

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_folder_search.py
"""

import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QImage

from app.core import i18n
from app.core.i18n import tr
from app.ui import local_viewer as lv
from app.ui.local_viewer import LocalViewer

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(app, cond, timeout_s: float = 20.0) -> bool:
    """Крутить цикл событий, пока условие не выполнится (или таймаут)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
        app.processEvents()
    return bool(cond())


def np(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class FakeSI:
    """Подменённый QStorageInfo: единственный «диск» — тестовая папка."""

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


def main() -> int:
    # --- тестовая файловая система ---
    tmp_root = tempfile.mkdtemp(prefix="ih_fs_root_")     # «домашняя папка» (пустая)
    base = tempfile.mkdtemp(prefix="ih_fs_base_")         # единственный «диск»

    def mk(rel: str) -> str:
        path = os.path.join(base, rel)
        os.makedirs(path, exist_ok=True)
        return path

    target_one = mk("Albums/TargetOne")
    docs = mk("docs")                     # «выбранная папка» для проверки области поиска
    target_two = mk("docs/TargetTwo")
    deeper = mk("docs/deep/DeeperTarget")
    target_photos = mk("photos/TargetPhotos")
    sub_of_target = mk("photos/TargetPhotos/SubFolder")
    mk("photos/usual")
    target_file = mk("TargetFile")
    os.makedirs(os.path.join(base, ".hidden/TargetSecret"), exist_ok=True)
    with open(os.path.join(base, "TargetFile.txt"), "w") as f:
        f.write("файл, не папка")

    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(0xFF00FF00)
    assert img.save(os.path.join(target_one, "pic.png"))

    expected = {target_one, target_two, deeper, target_photos, target_file}

    # --- подмена окружения: дом = tmp_root, один диск = base ---
    class _Loc:
        HomeLocation = 0
        PicturesLocation = 1
        GenericCacheLocation = 2

    class FakeStdPaths:
        StandardLocation = _Loc

        @staticmethod
        def writableLocation(_kind) -> str:
            return tmp_root

    lv.QStandardPaths = FakeStdPaths
    lv.QStorageInfo = types.SimpleNamespace(
        mountedVolumes=lambda: [FakeSI(base)])

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    i18n.set_lang("ru", persist=False)

    viewer = LocalViewer()
    viewer.resize(900, 900)
    viewer.show()
    app.processEvents()

    # 1. корни поиска: Домой + единственный диск
    roots = viewer._search_roots()
    check("корни поиска = Домой + диск", np(tmp_root) in map(np, roots) and np(base) in map(np, roots),
          str(roots))

    # 2. обычное дерево построено из подменённых корней
    tops = [viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(viewer.tree.topLevelItemCount())]
    check("дерево: дом и диск на верхнем уровне",
          np(tmp_root) in map(np, tops) and np(base) in map(np, tops), str(tops))

    # 3. поиск: дебаунс + фоновый обход, результаты появляются в дереве
    viewer.folder_search.setText("target")
    ok = wait_until(app, lambda: viewer._fs_in_search and viewer._fs_handle is None
                    and viewer._fs_count == 5)
    check("поиск «target» нашёл все 5 папок", ok,
          f"in_search={viewer._fs_in_search} count={viewer._fs_count}")
    got = {viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
           for i in range(viewer.tree.topLevelItemCount())}
    check("совпадения совпадают с ожидаемыми (регистр не важен)",
          {np(p) for p in got} == {np(p) for p in expected}, str(got))

    # 4. фильтры: скрытые папки и файлы не попадают
    all_got = "\n".join(sorted(got))
    check("скрытые папки пропущены", ".hidden" not in all_got)
    check("файлы не попадают в результаты (только папки)", "TargetFile.txt" not in all_got)

    # 5. оформление результата: 2 колонки, путь родителя, подсказка, «Найдено папок»
    check("дерево в режиме результатов (2 колонки)", viewer.tree.columnCount() == 2)
    first = viewer.tree.topLevelItem(0)
    check("родительский путь во второй колонке",
          first.text(1) == os.path.dirname(first.data(0, Qt.ItemDataRole.UserRole)),
          first.text(1))
    check("подсказка = полный путь",
          first.toolTip(0) == first.data(0, Qt.ItemDataRole.UserRole))
    check("счётчик найденного показан", viewer.tree_info.isVisible()
          and "5" in viewer.tree_info.text(), viewer.tree_info.text())
    check("первый результат выделен",
          viewer.tree.currentItem() is viewer.tree.topLevelItem(0))

    # 6. клик по результату открывает папку (и поиск не сбрасывается)
    item_one = next(viewer.tree.topLevelItem(i) for i in range(viewer.tree.topLevelItemCount())
                    if np(viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole))
                    == np(target_one))
    viewer.tree.itemClicked.emit(item_one, 0)
    check("клик по результату открыл папку", viewer.current_folder() == target_one,
          viewer.current_folder())
    check("картинки папки загрузились (1 png)", viewer.list.count() == 1)
    check("режим поиска не сброшен кликом", viewer._fs_in_search)

    # 7. результат можно раскрыть прямо в дереве (ленивые подпапки)
    photos_item = next(viewer.tree.topLevelItem(i) for i in range(viewer.tree.topLevelItemCount())
                       if np(viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole))
                       == np(target_photos))
    check("родитель вложенной находки виден серым путём",
          next(viewer.tree.topLevelItem(i) for i in range(viewer.tree.topLevelItemCount())
               if np(viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole))
               == np(deeper)).text(1) == os.path.join(base, "docs", "deep"))
    viewer._populate_children(photos_item)
    kids = [photos_item.child(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(photos_item.childCount())]
    check("раскрытие результата показывает подпапки", kids == [sub_of_target], f"{kids}")

    # 8. Enter открывает первый (выделенный) результат
    viewer.tree.setCurrentItem(viewer.tree.topLevelItem(0))
    viewer.folder_search.returnPressed.emit()
    check("Enter открыл первый результат",
          viewer.current_folder()
          == viewer.tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole),
          viewer.current_folder())

    # 9. смена языка не затирает результаты поиска
    i18n.set_lang("en", persist=False)
    app.processEvents()
    check("после смены языка результаты на месте",
          viewer._fs_in_search and viewer.tree.topLevelItemCount() == 5)
    check("счётчик переведён (Folders found: 5)",
          "Folders found: 5" in viewer.tree_info.text(), viewer.tree_info.text())
    check("плейсхолдер переведён", "Search folders" in viewer.folder_search.placeholderText())
    i18n.set_lang("ru", persist=False)
    app.processEvents()

    # 10. очистка поля возвращает обычное дерево и подсвечивает текущую папку
    viewer.folder_search.clear()
    app.processEvents()
    check("поле очищено — режим поиска выключен", not viewer._fs_in_search)
    check("дерево снова с одной колонкой", viewer.tree.columnCount() == 1)
    check("счётчик скрыт", not viewer.tree_info.isVisible())
    tops_after = [viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                  for i in range(viewer.tree.topLevelItemCount())]
    check("обычное дерево восстановлено", np(tmp_root) in map(np, tops_after)
          and np(base) in map(np, tops_after), str(tops_after))
    cur = viewer.tree.currentItem()
    cur_path = cur.data(0, Qt.ItemDataRole.UserRole) if cur else None
    check("текущая папка подсвечена в дереве", cur_path == viewer.current_folder(),
          f"{cur_path} vs {viewer.current_folder()}")

    # 11. повторный поиск + Esc в поле (фокус в поле) — сброс.
    #     Выбор папки сбрасываем: имитируем «ничего не выбрано» — глобальный поиск.
    viewer._folder = ""
    viewer.folder_search.setFocus()
    app.processEvents()
    viewer.folder_search.setText("target")
    ok = wait_until(app, lambda: viewer._fs_handle is None and viewer._fs_count == 5)
    check("повторный поиск работает", ok, f"count={viewer._fs_count}")
    viewer._escape_search()
    app.processEvents()
    check("Esc очистил поле поиска папок", viewer.folder_search.text() == "")
    check("Esc вернул обычное дерево", not viewer._fs_in_search)

    # 12. Esc при фокусе вне поля чистит поиск по имени (прежнее поведение)
    viewer.search_edit.setText("заглушка")
    viewer.folder_search.clearFocus()
    viewer.setFocus()
    app.processEvents()
    viewer._escape_search()
    check("Esc вне поля чистит поиск по имени", viewer.search_edit.text() == "")

    # 13. запрос без совпадений: «Папок с таким именем не найдено», дерево пустое
    viewer.folder_search.setText("нет_такой_папки")
    ok = wait_until(app, lambda: viewer._fs_handle is None and viewer._fs_in_search
                    and viewer.tree.topLevelItemCount() == 0)
    check("без совпадений дерево пустое", ok)
    check("сообщение «не найдено»", "не найдено" in viewer.tree_info.text(),
          viewer.tree_info.text())
    viewer.folder_search.clear()
    app.processEvents()

    # 14. ⟳ выходит из режима поиска и перечитывает корни
    viewer.folder_search.setText("target")
    wait_until(app, lambda: viewer._fs_handle is None and viewer._fs_count == 5)
    viewer._on_tree_refresh_clicked()
    app.processEvents()
    check("⟳ сбросил поиск и очистил поле",
          not viewer._fs_in_search and viewer.folder_search.text() == "")

    # 15. юнит: пересекающиеся корни — без дублей и без двойного обхода
    sig = lv._FolderSearchSignals()
    batches: list[list[str]] = []
    dones: list[tuple[int, bool]] = []
    sig.batch.connect(lambda g, items: batches.append(list(items)))
    sig.done.connect(lambda g, total, trunc: dones.append((total, trunc)))
    task = lv._FolderSearchTask([base, os.path.join(base, "docs")], "TaRgEt", 1,
                                sig, lv._SearchHandle())
    task.run()   # синхронно, в главном потоке
    flat = [p for b in batches for p in b]
    check("пересекающиеся корни: дублей нет",
          dones and dones[0][0] == 5 and len(flat) == 5
          and len({np(p) for p in flat}) == 5, f"{dones} flat={len(flat)}")

    # 16. юнит: усечение выдачи по MAX_RESULTS
    old_max = lv._FolderSearchTask.MAX_RESULTS
    try:
        lv._FolderSearchTask.MAX_RESULTS = 2
        batches.clear()
        dones.clear()
        task2 = lv._FolderSearchTask([base], "target", 2, sig, lv._SearchHandle())
        task2.run()
        flat2 = [p for b in batches for p in b]
        check("усечение: найдено ровно 2, помечено как усечённое",
              dones and dones[0] == (2, True) and len(flat2) == 2, f"{dones}")
    finally:
        lv._FolderSearchTask.MAX_RESULTS = old_max

    # 17. юнит: отмена задачи не эмитит done
    handle3 = lv._SearchHandle()
    dones.clear()
    task3 = lv._FolderSearchTask([base], "target", 3, sig, handle3)
    handle3.cancelled = True
    task3.run()
    check("отменённая задача молчит", not dones)

    # 18. новые i18n-ключи есть во всех трёх языках
    need = ["viewer.folders_search_ph", "viewer.folders_search_tip",
            "viewer.folders_searching", "viewer.folders_searching_in",
            "viewer.folders_searching_found", "viewer.folders_searching_in_found",
            "viewer.folders_scope_all", "viewer.folders_found",
            "viewer.folders_found_in", "viewer.folders_none", "viewer.folders_trunc",
            "log.event.folder_search", "log.event.folder_search_done"]
    for key in need:
        langs = i18n._STRINGS.get(key, {})
        check(f"i18n {key}: ru/en/zh",
              all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
    check("tr() подставляет {n}", tr("viewer.folders_found", n=7) != "viewer.folders_found")
    check("tr() подставляет {where}",
          tr("viewer.folders_searching_in", where="X") != "viewer.folders_searching_in")

    # 19. поиск по имени ищет только ВНУТРИ выбранной папки, а не по всей системе
    viewer._folder = ""
    viewer.load_folder(docs)
    check("выбранная папка запомнена", viewer.current_folder() == docs,
          viewer.current_folder())
    viewer.folder_search.setText("target")
    ok = wait_until(app, lambda: viewer._fs_handle is None and viewer._fs_in_search
                    and viewer.tree.topLevelItemCount() == 2)
    check("в выбранной папке найдены только её подпапки (2)", ok,
          f"count={viewer._fs_count}")
    got_scope = {viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                 for i in range(viewer.tree.topLevelItemCount())}
    check("за пределами выбранной папки ничего не найдено",
          {np(p) for p in got_scope} == {np(target_two), np(deeper)}, str(got_scope))
    check("область поиска показана в статусе", "docs" in viewer.tree_info.text(),
          viewer.tree_info.text())

    # 20. очистка поля возвращает дерево; выбранная папка сохраняется
    viewer.folder_search.clear()
    app.processEvents()
    check("очистка вышла из режима поиска", not viewer._fs_in_search)
    check("выбранная папка сохранилась после поиска", viewer.current_folder() == docs,
          viewer.current_folder())

    # 21. юнит: задача от выбранного корня не выходит за его пределы
    batches.clear()
    dones.clear()
    task4 = lv._FolderSearchTask([docs], "target", 4, sig, lv._SearchHandle())
    task4.run()
    flat4 = [p for b in batches for p in b]
    check("юнит: обход строго внутри выбранной папки",
          dones and dones[-1][0] == 2
          and {np(p) for p in flat4} == {np(target_two), np(deeper)},
          f"{dones} {flat4}")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt: известные abort'ы при разрушении виджетов в песочнице
