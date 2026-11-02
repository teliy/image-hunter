"""Оффлайн-тест асинхронной прогулки дерева к текущей папке (v0.7.6).

Репорт: после обновления в «Моих картинках» фильтр и картинки восстановились,
но не видно, в какой папке они находятся, — дерево оставалось свёрнутым.
Причина: подсветка была привязана к результату фонового скана папки, а
восстановленный поиск по имени обгонял скан и отбрасывал его вместе с
подсветкой. Теперь дерево раскрывается к папке сразу и асинхронно.

Проверяется:
- _sync_tree_async доходит до глубокой папки и подсвечивает её;
- несуществующая папка — подсветка ближайшего существующего узла;
- старт с восстановленной папкой И фильтром — дерево раскрыто (регресс);
- открытие папки через «диалог» (load_folder sync_tree=True) — подсветка.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_tree_sync.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QStandardPaths, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.local_viewer import LocalViewer  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def np(path: str) -> str:
    return os.path.normpath(path)


def current_path(viewer: LocalViewer) -> str:
    it = viewer.tree.currentItem()
    return np(it.data(0, Qt.ItemDataRole.UserRole) or "") if it else ""


def item_by_path(viewer: LocalViewer, path: str):
    want = np(path)
    stack = [viewer.tree.topLevelItem(i)
             for i in range(viewer.tree.topLevelItemCount())]
    while stack:
        it = stack.pop()
        if np(it.data(0, Qt.ItemDataRole.UserRole) or "") == want:
            return it
        stack.extend(it.child(i) for i in range(it.childCount()))
    return None


def expanded_chain_ok(viewer: LocalViewer, path: str) -> bool:
    """Все узлы пути до folder раскрыты (кроме самой папки — не обязательно)."""
    node = item_by_path(viewer, path)
    while node is not None:
        parent = node.parent()
        if parent is not None and not parent.isExpanded():
            return False
        node = parent
    return True


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")

    # дерево знает только реальные диски и Домой; в песочнице / — overlay
    # (виртуальный), поэтому папки создаём внутри Home — как у пользователя
    home = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)
    root = tempfile.mkdtemp(prefix="ih_tree_sync_", dir=home)
    a = os.path.join(root, "a")
    ab = os.path.join(a, "b")
    abc = os.path.join(ab, "c")
    other = os.path.join(root, "other")
    for d in (a, ab, abc, other):
        os.makedirs(d, exist_ok=True)

    def wait_until(cond, timeout_s: float = 15.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            app.processEvents()
            if cond():
                time.sleep(0.05)
                app.processEvents()
                return True
            time.sleep(0.02)
        return False

    try:
        viewer = LocalViewer()   # last_folder пуст — автопоказа нет

        # 1. асинхронная прогулка доходит до глубокой папки и подсвечивает её
        viewer._sync_tree_async(abc)
        ok = wait_until(lambda: current_path(viewer) == np(abc))
        check("дерево раскрылось до глубокой папки и подсветило её", ok,
              f"current={current_path(viewer)!r}")
        check("все уровни пути раскрыты", expanded_chain_ok(viewer, abc))

        # 2. несуществующая папка — подсветка ближайшего существующего узла
        ghost = os.path.join(a, "b", "нет_такой")
        viewer._sync_tree_async(ghost)
        ok = wait_until(lambda: current_path(viewer) == np(ab))
        check("несуществующая папка — подсвечен ближайший узел", ok,
              f"current={current_path(viewer)!r}")

        # 3. регресс: старт с восстановленной папкой И фильтром —
        #    раньше поиск обгонял скан и сбрасывал подсветку вместе с ним
        st.setValue("viewer/last_folder", abc)
        st.setValue("viewer/last_query", "img")
        viewer2 = LocalViewer()
        check("запрос фильтра восстановлен",
              viewer2.search_edit.text() == "img", viewer2.search_edit.text())
        ok = wait_until(lambda: current_path(viewer2) == np(abc))
        check("при старте с фильтром дерево раскрыто к папке с картинками", ok,
              f"current={current_path(viewer2)!r}")
        check("все уровни пути раскрыты (старт с фильтром)",
              expanded_chain_ok(viewer2, abc))

        # 4. открытие папки через «диалог» (load_folder sync_tree=True);
        #    настройки восстановлений чистим — viewer3 должен стартовать пустым
        st.setValue("viewer/last_folder", "")
        st.setValue("viewer/last_query", "")
        viewer3 = LocalViewer()
        viewer3.load_folder(other, sync_tree=True)
        ok = wait_until(lambda: current_path(viewer3) == np(other))
        check("load_folder(sync_tree=True) подсвечивает папку", ok,
              f"current={current_path(viewer3)!r}")
    finally:
        st.setValue("viewer/last_folder", "")
        st.setValue("viewer/last_query", "")
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
