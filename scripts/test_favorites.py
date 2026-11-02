"""Оффлайн-тест избранных папок в дереве «Диски и папки» (v0.7.9).

Проверяется:
- fav_add ставит папку с звездой на самый верх дерева, до «Домой» и дисков;
- повторное добавление (другое написание пути) не плодит дубликатов;
- порядок избранного — в порядке добавления;
- избранное переживает перезапуск (QSettings) и refresh_drives;
- fav_remove убирает узел, остальное избранное на месте;
- кнопка ☆/★: без папки выключена, с папкой меняет вид;
- клик по избранному открывает папку (как обычный узел дерева);
- после удаления избранного, внутри которого мы находились, подсветка
  возвращается к текущей папке.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_favorites.py
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

from app.ui.local_viewer import LocalViewer, _FAV_ROLE  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def np(path: str) -> str:
    return os.path.normpath(path)


def top_paths(viewer: LocalViewer) -> list[str]:
    return [np(viewer.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) or "")
            for i in range(viewer.tree.topLevelItemCount())]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    st.setValue("viewer/favorites", [])

    home = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)
    root = tempfile.mkdtemp(prefix="ih_fav_", dir=home)
    brand1 = os.path.join(root, "BMW")
    brand2 = os.path.join(root, "AUDI")
    deep = os.path.join(brand1, "2024")
    for d in (brand1, brand2, deep):
        os.makedirs(d, exist_ok=True)

    def wait_until(cond, timeout_s: float = 10.0) -> bool:
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
        viewer = LocalViewer()
        check("без избранного верх дерева — не избранный узел",
              not viewer.tree.topLevelItem(0).data(0, _FAV_ROLE),
              top_paths(viewer)[:2].__str__())

        # 1. добавление: избранный узел — самый верхний, с ролью и звездой
        viewer.fav_add(brand1)
        it = viewer.tree.topLevelItem(0)
        check("избранная папка — верхний узел дерева",
              np(it.data(0, Qt.ItemDataRole.UserRole)) == np(brand1),
              top_paths(viewer)[:2].__str__())
        check("узел помечен как избранный", bool(it.data(0, _FAV_ROLE)))
        check("иконка звезды не пустая", not it.icon(0).isNull())
        check("подсказка — полный путь", it.toolTip(0) == brand1, it.toolTip(0))
        check("подпись — имя папки", it.text(0) == "BMW", it.text(0))
        check("узел раскрываемый (есть заглушка)",
              it.childCount() == 1 and not it.child(0).data(0, Qt.ItemDataRole.UserRole))
        check("избранное старше «Домой»",
              top_paths(viewer)[1] != np(brand1)
              and not viewer.tree.topLevelItem(1).data(0, _FAV_ROLE))

        # 2. то же самое в другом написании — дубликата нет
        viewer.fav_add(brand1 + os.sep)
        check("дубликат (другое написание) не добавлен",
              len(viewer._favorites) == 1
              and top_paths(viewer).count(np(brand1)) == 1,
              str(viewer._favorites))
        viewer.fav_add("")
        check("пустой путь игнорируется", len(viewer._favorites) == 1)

        # 3. вторая папка — порядок добавления сохраняется
        viewer.fav_add(brand2)
        check("два избранных в порядке добавления",
              top_paths(viewer)[:2] == [np(brand1), np(brand2)],
              top_paths(viewer)[:3].__str__())
        check("настройки получили оба пути",
              sorted(st.value("viewer/favorites") or []) == sorted([np(brand1), np(brand2)]),
              str(st.value("viewer/favorites")))

        # 4. перезапуск: новый вьюер показывает избранное первым
        viewer2 = LocalViewer()
        check("после «перезапуска» избранное всё ещё первое",
              top_paths(viewer2)[:2] == [np(brand1), np(brand2)],
              top_paths(viewer2)[:3].__str__())

        # 5. refresh_drives (смена языка, кнопка ⟳) избранное не теряет
        viewer.refresh_drives()
        check("refresh_drives оставил избранное сверху",
              top_paths(viewer)[:2] == [np(brand1), np(brand2)],
              top_paths(viewer)[:3].__str__())

        # 6. кнопка ☆/★
        check("кнопка ☆ выключена без папки", not viewer.btn_fav.isEnabled())
        viewer.load_folder(deep, entries=[])
        check("кнопка ☆ включена, когда папка открыта",
              viewer.btn_fav.isEnabled() and viewer.btn_fav.text() == "☆",
              f"enabled={viewer.btn_fav.isEnabled()} text={viewer.btn_fav.text()}")
        viewer._on_fav_button()
        check("клик по ☆ добавил текущую папку",
              viewer.is_favorite(deep) and viewer.btn_fav.text() == "★",
              f"text={viewer.btn_fav.text()} favorites={viewer._favorites}")
        check("избранное в дереве содержит текущую папку",
              np(deep) in top_paths(viewer)[:3], top_paths(viewer)[:4].__str__())
        viewer._on_fav_button()
        check("повторный клик по ★ убрал папку",
              not viewer.is_favorite(deep) and viewer.btn_fav.text() == "☆",
              f"text={viewer.btn_fav.text()} favorites={viewer._favorites}")

        # 7. fav_remove: узел исчезает, остальное избранное цело;
        #    чужая папка — no-op
        n_before = len(viewer._favorites)
        viewer.fav_remove(os.path.join(root, "нет такой"))
        check("удаление не-избранного ничего не меняет",
              len(viewer._favorites) == n_before)
        viewer.fav_remove(brand1)
        check("fav_remove убрал узел из дерева",
              np(brand1) not in top_paths(viewer) and np(brand2) in top_paths(viewer),
              top_paths(viewer)[:3].__str__())
        check("в списке осталась одна папка",
              viewer._favorites == [np(brand2)], str(viewer._favorites))

        # 8. клик по избранному открывает папку (как обычный узел)
        fav_item = viewer.tree.topLevelItem(0)
        viewer._on_tree_clicked(fav_item, 0)
        check("клик по избранному открыл папку",
              np(viewer._folder) == np(brand2), viewer._folder)

        # 9. удалили избранное, внутри которого мы сейчас, — подсветка
        #    возвращается к текущей папке (уже через обычное дерево)
        sub = os.path.join(brand2, "детали")
        os.makedirs(sub, exist_ok=True)
        viewer.fav_add(brand2)
        viewer.load_folder(sub, entries=[], sync_tree=True)
        check("текущая папка — внутри избранной",
              np(viewer._folder) == np(sub)
              and top_paths(viewer)[0] == np(brand2),
              f"folder={viewer._folder} top={top_paths(viewer)[:1]}")
        viewer.fav_remove(brand2)
        ok = wait_until(lambda: viewer.tree.currentItem() is not None
                        and np(viewer.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) or "")
                        in (np(sub), np(brand2)))
        check("после удаления избранного подсветка вернулась к текущей папке", ok,
              f"current={viewer.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if viewer.tree.currentItem() else None}")
    finally:
        st.setValue("viewer/last_folder", "")
        st.setValue("viewer/last_query", "")
        st.setValue("viewer/favorites", [])
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
