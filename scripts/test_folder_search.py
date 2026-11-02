"""Оффлайн-тест фильтра папок в дереве «Диски и папки».

Ввод букв скрывает папки, в имени которых их нет: совпавшие папки и их
предки остаются видимы, ветки к совпавшим раскрываются, счётчик показывается
над деревом. Дерево ленивое — фильтр сам догружает уровни (с бюджетом папок
и секунд), чтобы буквы находили и вложенные папки.

С v0.7.10 у фильтра есть область: ищется вглубь ВЫДЕЛЕННОЙ папки или диска
(что подсвечено в дереве), чужие верхние ветки прячутся целиком; ничего
не выделено — поиск по всему дереву, как раньше.

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
    """Пути папок, РЕАЛЬНО видимых в дереве: узел скрыт, если скрыт он сам
    или любой его предок (сырого флага isHidden() мало — фильтр с областью
    прячет чужие ветки целиком, не трогая флаги их потомков)."""
    out: set = set()

    def walk(item, parent_visible: bool) -> None:
        for j in range(item.childCount()):
            child = item.child(j)
            vis = parent_visible and not child.isHidden()
            p = child.data(0, Qt.ItemDataRole.UserRole)
            if p and vis:
                out.add(np(p))
            walk(child, vis)

    walk(viewer.tree.invisibleRootItem(), True)
    return out


def item_by_path(viewer, path: str):
    """Узел дерева по пути папки."""
    want = np(path)
    for item in walk_items(viewer.tree.invisibleRootItem()):
        p = item.data(0, Qt.ItemDataRole.UserRole)
        if p and np(p) == want:
            return item
    return None


def effectively_visible(item) -> bool:
    """Виден ли узел реально: без hidden у себя и у всех предков."""
    it = item
    while it is not None:
        if it.isHidden():
            return False
        it = it.parent()
    return True


def focus_folder(viewer, path: str):
    """Эмуляция клика мышью по папке: мышинный клик в Qt меняет и currentItem
    (фокус/область фильтра), и открывает папку. Программный emit сигнала
    itemClicked меняет только второе — выделение ставим явно."""
    it = item_by_path(viewer, path)
    viewer.tree.setCurrentItem(it)
    viewer.tree.itemClicked.emit(it, 0)
    return it


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
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/favorites", [])
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
    wait_until(app, lambda: viewer.list.count() == 1)
    check("картинки папки загрузились (1 png)", viewer.list.count() == 1)
    check("фильтр не сброшен кликом", viewer.tree_info.isVisible())

    # 6. Enter открывает первую совпавшую папку (фильтр применяется сразу,
    #    не дожидаясь дебаунса). Область фильтра задаёт фокус (v0.7.10):
    #    выделяем docs — ищем внутри неё
    focus_folder(viewer, docs)
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

    # 11. запрос без совпадений: скрыто всё, кроме пути к фокусу,
    #     сообщение «не найдено» называет место поиска
    viewer.folder_search.setText("нет_такой_папки")
    wait_until(app, lambda: viewer.tree_info.isVisible()
               and "не найдено" in viewer.tree_info.text())
    vis = visible_paths(viewer)
    check("без совпадений скрыто всё, кроме пути к фокусу",
          vis == {np(base), np(docs), np(os.path.join(base, "docs", "deep"))},
          str(sorted(vis)))
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
    #     (после ⟳ диск уже загружен через _sync_tree; область — фокус на photos)
    focus_folder(viewer, photos)
    viewer.folder_search.setText("sub")       # дебаунс ещё не истёк
    viewer._populate_children(item_by_path(viewer, photos))   # «раскрыли» папку вручную
    ok = wait_until(app, lambda: np(sub_of_target) in visible_paths(viewer)
                    and np(usual) not in visible_paths(viewer))
    check("раскрытие при фильтре сразу применило фильтр", ok,
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

    # 15а. область фильтра (v0.7.10): появляется второй «диск» с папками;
    #      фокус на диске — буквы ищутся вглубь только его, чужой диск скрыт
    base2 = tempfile.mkdtemp(prefix="ih_fs_disk2_")
    daewoo = os.path.join(base2, "DaewooStuff")
    inside_box = os.path.join(daewoo, "InsideBox")
    alpha_stuff = os.path.join(base2, "AlphaStuff")
    beta_stuff = os.path.join(base2, "BetaStuff")
    for d in (daewoo, inside_box, alpha_stuff, beta_stuff):
        os.makedirs(d, exist_ok=True)
    lv.QStorageInfo = types.SimpleNamespace(
        mountedVolumes=lambda: [FakeSI(base), FakeSI(base2)])
    viewer.refresh_drives()
    app.processEvents()
    disk2_item = item_by_path(viewer, base2)
    check("второй диск появился в дереве", disk2_item is not None)

    focus_folder(viewer, base2)   # фокус — второй диск
    viewer.folder_search.setText("inside")
    ok = wait_until(app, lambda: {p for p in visible_paths(viewer)
                                  if "inside" in os.path.basename(p).lower()}
                    == {np(inside_box)})
    check("фокус на диске: совпадение найдено внутри него", ok,
          viewer.tree_info.text())
    got = {p for p in visible_paths(viewer)
           if "inside" in os.path.basename(p).lower()}
    check("фокус на диске: ищутся только его папки", got == {np(inside_box)},
          str(sorted(got)))
    check("чужой диск скрыт целиком",
          item_by_path(viewer, base).isHidden()
          and not item_by_path(viewer, base2).isHidden())
    check("счётчик показывает область поиска",
          np(base2) in viewer.tree_info.text(), viewer.tree_info.text())
    check("событие журнала с областью записано",
          any(k == "log.event.folder_filter_in"
              and kw.get("q") == "inside" and kw.get("n") == 1
              for k, kw in events), str(events[-3:]))

    # 15б. фокус на глубокой папке: совпадения вне её не находятся,
    #      сообщение «не найдено» называет место поиска
    focus_folder(viewer, inside_box)
    app.processEvents()
    viewer.folder_search.setText("alpha")
    ok = wait_until(app, lambda: viewer.tree_info.isVisible()
                    and "не найдено" in viewer.tree_info.text())
    check("узкий фокус: совпадение вне его не найдено", ok,
          viewer.tree_info.text())
    check("в сообщении названо место поиска",
          "InsideBox" in viewer.tree_info.text(), viewer.tree_info.text())
    check("чужая ветка скрыта даже с совпадением",
          not effectively_visible(item_by_path(viewer, alpha_stuff)))
    viewer.folder_search.returnPressed.emit()   # Enter не уведёт вне области
    check("Enter не открыл папку вне области поиска",
          viewer.current_folder() == inside_box, viewer.current_folder())

    # 15в. фокус на диске снова: «alpha» находит папку на своём диске
    focus_folder(viewer, base2)
    viewer.folder_search.setText("alpha")
    ok = wait_until(app, lambda: np(alpha_stuff) in visible_paths(viewer))
    check("фокус на диске: папка своего диска найдена", ok,
          str(sorted(visible_paths(viewer))))
    check("чужой диск по-прежнему скрыт",
          item_by_path(viewer, base).isHidden()
          and not effectively_visible(item_by_path(viewer, beta_stuff)))

    # 15г. ничего не выделено — поиск по всему дереву, как раньше
    viewer.tree.setCurrentItem(None)
    viewer.folder_search.setText("target")
    # ждём ТОЧНО нескоупленную строку (не подстроку «5» — hex пути мог её содержать)
    ok = wait_until(app, lambda: "Найдено папок: 5" in viewer.tree_info.text())
    check("без фокуса ищется везде (все 5 папок)", ok,
          viewer.tree_info.text())
    check("без фокуса чужой диск видим", not item_by_path(viewer, base).isHidden())
    viewer.folder_search.clear()
    app.processEvents()

    # 16. новые i18n-ключи есть во всех трёх языках
    need = ["viewer.folders_search_ph", "viewer.folders_search_tip",
            "viewer.folders_found", "viewer.folders_found_in",
            "viewer.folders_none", "viewer.folders_none_in",
            "log.event.folder_filter", "log.event.folder_filter_in"]
    for key in need:
        langs = i18n._STRINGS.get(key, {})
        check(f"i18n {key}: ru/en/zh",
              all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
    old = [k for k in i18n._STRINGS
           if "folder_search" in k or "folders_searching" in k
           or "folders_scope" in k or "folders_trunc" in k]
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
