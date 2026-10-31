"""Оффлайн-тест фильтра папок в дереве «Диски и папки».

Ввод букв скрывает папки, в имени которых их нет: совпавшие папки и их
предки остаются видимы, ветки к совпавшим раскрываются, счётчик показывается
над деревом. Дерево ленивое — фильтр сам догружает уровни (с бюджетом папок
и секунд), чтобы буквы находили и вложенные папки.

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


def wait_until(app, cond, timeout_s: float = 10.0) -> bool:
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


def walk_items(item):
    """Все узлы ПОД item (сам item не возвращается — невидимый корень не папка)."""
    for j in range(item.childCount()):
        yield item.child(j)
        yield from walk_items(item.child(j))


def real_paths(viewer) -> set:
    """Пути всех реальных папок, загруженных в дерево."""
    return {np(item.data(0, Qt.ItemDataRole.UserRole))
            for item in walk_items(viewer.tree.invisibleRootItem())
            if item.data(0, Qt.ItemDataRole.UserRole)}


def visible_paths(viewer) -> set:
    """Пути видимых (не скрытых фильтром) папок."""
    return {np(item.data(0, Qt.ItemDataRole.UserRole))
            for item in walk_items(viewer.tree.invisibleRootItem())
            if item.data(0, Qt.ItemDataRole.UserRole) and not item.isHidden()}


def item_by_path(viewer, path: str):
    """Узел дерева по пути папки."""
    want = np(path)
    for item in walk_items(viewer.tree.invisibleRootItem()):
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if p and np(p) == want:
            return item
    return None


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
    docs = mk("docs")
    target_two = mk("docs/TargetTwo")
    deeper = mk("docs/deep/DeeperTarget")
    photos = mk("photos")
    target_photos = mk("photos/TargetPhotos")
    sub_of_target = mk("photos/TargetPhotos/SubFolder")
    usual = mk("photos/usual")
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
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    i18n.set_lang("ru", persist=False)

    # журнал — подменяем, чтобы проверять события
    events: list[tuple] = []
    real_log = lv.applog.event
    lv.applog.event = lambda key, **kw: events.append((key, kw))

    viewer = LocalViewer()
    viewer.resize(900, 900)
    viewer.show()
    app.processEvents()

    # 1. обычное дерево построено из подменённых корней
    tops = [viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(viewer.tree.topLevelItemCount())]
    check("дерево: дом и диск на верхнем уровне",
          np(tmp_root) in map(np, tops) and np(base) in map(np, tops), str(tops))
    check("счётчик фильтра скрыт, пока поле пустое", not viewer.tree_info.isVisible())

    # 2. фильтр по дебаунсу (300 мс): «target» находит все 5 папок, включая вложенные
    viewer.folder_search.setText("target")
    ok = wait_until(app, lambda: viewer.tree_info.isVisible()
                    and "5" in viewer.tree_info.text())
    check("фильтр применился после паузы набора (дебаунс)", ok,
          viewer.tree_info.text())
    got = {p for p in visible_paths(viewer)
           if "target" in os.path.basename(p).lower()}
    check("«target» нашёл все 5 папок (регистр не важен)",
          got == {np(p) for p in expected}, str(sorted(got)))

    # 3. несовпадающие папки скрыты, предки совпавших видимы
    vis = visible_paths(viewer)
    check("скрытая папка .hidden не загружалась", ".hidden" not in str(vis))
    check("файлы не попадают в дерево", "TargetFile.txt" not in str(vis))
    check("непопавшая папка usual скрыта", np(usual) not in vis)
    check("подпапка без букв скрыта, хотя родитель совпал",
          np(sub_of_target) not in vis)
    check("предки совпавших папок видимы",
          all(np(p) in vis for p in (base, docs, photos,
                                     os.path.join(base, "Albums"),
                                     os.path.join(base, "docs", "deep"))))
    check("верхний уровень без совпадений скрыт", np(tmp_root) not in vis)
    check("ветка к совпавшей папке раскрылась",
          item_by_path(viewer, deeper).parent().isExpanded()
          and item_by_path(viewer, deeper).parent().parent().isExpanded())
    check("совпавшая папка без совпавших подпапок не раскрывается",
          not item_by_path(viewer, target_photos).isExpanded())

    # 4. оформление: счётчик над деревом, журнал
    check("счётчик найденного показан", "Найдено папок: 5" in viewer.tree_info.text(),
          viewer.tree_info.text())
    check("событие журнала записано",
          ("log.event.folder_filter", {"q": "target", "n": 5}) in events, str(events[-3:]))

    # 5. клик по совпавшей папке открывает её (фильтр не сбрасывается)
    item_one = item_by_path(viewer, target_one)
    viewer.tree.itemClicked.emit(item_one, 0)
    check("клик по результату открыл папку", viewer.current_folder() == target_one,
          viewer.current_folder())
    check("картинки папки загрузились (1 png)", viewer.list.count() == 1)
    check("фильтр не сброшен кликом", viewer.tree_info.isVisible())

    # 6. Enter открывает первую совпавшую папку (фильтр применяется сразу,
    #    не дожидаясь дебаунса)
    viewer.folder_search.setText("deeper")
    viewer.folder_search.returnPressed.emit()
    check("Enter открыл единственную совпавшую папку",
          viewer.current_folder() == deeper, viewer.current_folder())
    check("после Enter в счётчике 1", "1" in viewer.tree_info.text(),
          viewer.tree_info.text())

    # 7. смена языка перечитывает дерево и заново применяет фильтр
    i18n.set_lang("en", persist=False)
    app.processEvents()
    check("счётчик переведён (Folders found: 1)",
          "Folders found: 1" in viewer.tree_info.text(), viewer.tree_info.text())
    check("плейсхолдер переведён", "Filter folders" in viewer.folder_search.placeholderText())
    i18n.set_lang("ru", persist=False)
    app.processEvents()

    # 8. очистка поля возвращает всё дерево
    viewer.folder_search.clear()
    app.processEvents()
    check("счётчик скрыт", not viewer.tree_info.isVisible())
    loaded = real_paths(viewer)
    check("все загруженные папки снова видимы", visible_paths(viewer) == loaded,
          f"{len(loaded)} папок")
    check("обычное дерево с корнями восстановлено",
          np(tmp_root) in visible_paths(viewer) and np(base) in visible_paths(viewer))
    cur = viewer.tree.currentItem()
    cur_path = cur.data(0, Qt.ItemDataRole.UserRole) if cur else None
    check("текущая папка подсвечена в дереве", cur_path == viewer.current_folder(),
          f"{cur_path} vs {viewer.current_folder()}")

    # 9. Esc в поле чистит фильтр
    viewer.folder_search.setFocus()
    app.processEvents()
    viewer.folder_search.setText("target")
    wait_until(app, lambda: viewer.tree_info.isVisible())
    viewer._escape_search()
    app.processEvents()
    check("Esc очистил поле фильтра", viewer.folder_search.text() == "")
    check("после Esc все папки видимы",
          visible_paths(viewer) == real_paths(viewer))

    # 10. Esc вне поля чистит поиск по имени (прежнее поведение)
    viewer.search_edit.setText("заглушка")
    viewer.folder_search.clearFocus()
    viewer.setFocus()
    app.processEvents()
    viewer._escape_search()
    check("Esc вне поля чистит поиск по имени", viewer.search_edit.text() == "")

    # 11. запрос без совпадений: все папки скрыты, сообщение «не найдено»
    viewer.folder_search.setText("нет_такой_папки")
    wait_until(app, lambda: viewer.tree_info.isVisible()
               and "не найдено" in viewer.tree_info.text())
    check("без совпадений все папки скрыты", not visible_paths(viewer))
    check("сообщение «не найдено»", "не найдено" in viewer.tree_info.text(),
          viewer.tree_info.text())
    viewer.folder_search.clear()
    app.processEvents()

    # 12. ⟳ снимает фильтр и перечитывает корни
    viewer.folder_search.setText("target")
    wait_until(app, lambda: viewer.tree_info.isVisible())
    viewer._on_tree_refresh_clicked()
    app.processEvents()
    check("⟳ сбросил фильтр и очистил поле",
          viewer.folder_search.text() == "" and not viewer.tree_info.isVisible())
    check("⟳ вернул корни дерева",
          np(tmp_root) in visible_paths(viewer) and np(base) in visible_paths(viewer))

    # 13. ручное раскрытие при активном фильтре — новые подпапки тоже фильтруются
    #     (после ⟳ диск уже загружен через _sync_tree, поэтому раскрываем photos)
    viewer.folder_search.setText("sub")       # дебаунс ещё не истёк
    viewer._populate_children(item_by_path(viewer, photos))   # «раскрыли» папку вручную
    app.processEvents()
    check("раскрытие при фильтре сразу применило фильтр",
          np(sub_of_target) in visible_paths(viewer)
          and np(target_photos) in visible_paths(viewer)
          and np(usual) not in visible_paths(viewer),
          str(sorted(visible_paths(viewer))))
    viewer.folder_search.clear()
    app.processEvents()

    # 14. бюджет догрузки: с крошечным бюджетом глубокие папки не находятся,
    #     но фильтр не виснет; после восстановления бюджета всё находится
    old_dir_budget, old_time_budget = lv._FS_DIR_BUDGET, lv._FS_TIME_BUDGET
    try:
        lv._FS_DIR_BUDGET, lv._FS_TIME_BUDGET = 1, 5.0
        viewer._folder = ""   # без текущей папки, иначе _sync_tree загрузит ветку в обход бюджета
        viewer.folder_search.setText("deeper")
        viewer.refresh_drives()   # свежее дерево; хвостовой вызов применит фильтр
        app.processEvents()
        check("бюджет исчерпан: глубокая папка не найдена, сообщение показано",
              not visible_paths(viewer) and "не найдено" in viewer.tree_info.text(),
              viewer.tree_info.text())
        lv._FS_DIR_BUDGET = old_dir_budget
        viewer._apply_folder_filter()   # повтор: дерево уже частично загружено
        app.processEvents()
        check("после восстановления бюджета папка найдена",
              np(deeper) in visible_paths(viewer)
              and np(os.path.join(base, "docs", "deep")) in visible_paths(viewer),
              str(sorted(visible_paths(viewer))))
    finally:
        lv._FS_DIR_BUDGET, lv._FS_TIME_BUDGET = old_dir_budget, old_time_budget
    viewer.folder_search.clear()
    app.processEvents()

    # 15. заглушки ленивой загрузки не видны при фильтре (частичная догрузка)
    lv._FS_DIR_BUDGET = 6
    viewer._folder = ""
    viewer.folder_search.setText("target")
    viewer.refresh_drives()       # хвостовой фильтр загрузит только 6 папок
    dummies = [item for item in walk_items(viewer.tree.invisibleRootItem())
               if not item.data(0, Qt.ItemDataRole.UserRole) and not item.isHidden()]
    check("заглушки скрыты при фильтре", not dummies,
          str([(d.parent().text(0), d.parent().isHidden()) for d in dummies]))
    lv._FS_DIR_BUDGET = old_dir_budget
    viewer._apply_folder_filter()
    app.processEvents()
    viewer.folder_search.clear()
    app.processEvents()

    # 16. новые i18n-ключи есть во всех трёх языках
    need = ["viewer.folders_search_ph", "viewer.folders_search_tip",
            "viewer.folders_found", "viewer.folders_none",
            "log.event.folder_filter"]
    for key in need:
        langs = i18n._STRINGS.get(key, {})
        check(f"i18n {key}: ru/en/zh",
              all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
    old = [k for k in i18n._STRINGS
           if "folder_search" in k or "folders_searching" in k
           or "folders_scope" in k or "folders_trunc" in k
           or "folders_found_in" in k]
    check("старые ключи скан-поиска удалены", not old, str(old))
    check("tr() подставляет {n}", tr("viewer.folders_found", n=7) != "viewer.folders_found")
    check("tr() подставляет {q}",
          tr("log.event.folder_filter", q="X", n=1) != "log.event.folder_filter")

    # 17. повторное применение фильтра не перечитывает уже загруженные папки
    viewer.folder_search.setText("target")
    wait_until(app, lambda: viewer.tree_info.isVisible())
    events.clear()
    lv.applog.event = lambda key, **kw: events.append((key, kw))  # шум от кликов убран
    before = real_paths(viewer)
    viewer._apply_folder_filter()
    app.processEvents()
    check("повторный фильтр идентичен (без перезагрузки)",
          real_paths(viewer) == before and len(before) >= 9, str(len(before)))
    check("событие журнала на повторном применении",
          ("log.event.folder_filter", {"q": "target", "n": 5}) in events, str(events))
    lv.applog.event = real_log

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt: известные abort'ы при разрушении виджетов в песочнице
