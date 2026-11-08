"""Оффлайн-тест переименования файлов в ленте «Моих картинок» (v0.8.1).

Пожелание: «добавь возможность переименовывать файлы, как по меню мыши,
так и 2-я кликами на название файла».

Проверяет:
1. чистку имени от редактора (_clean_rename_name) и проверку допустимости
   (_name_is_allowed: пустое, точки/пробелы на конце, запрещённые символы);
2. пункт меню «Переименовать» и клавишу F2 на ленте;
3. геометрию подписи плитки: клик по нижней полосе — имя, по иконке — нет;
4. маршрутизацию двойного клика: по имени → nameDoubleClicked (редактор),
   по картинке → itemDoubleClicked (открытие файла);
5. полный цикл переименования: файл на диске, _paths, плитка (текст, путь,
   подсказка), статус «Переименовано: старое → новое», событие в журнале;
6. редактор открывается с выделенным именем без расширения (как в
   Проводнике), Esc возвращает всё как было;
7. отказ для пустого имени и запрещённых символов — текст плитки
   возвращается, задача не стартует;
8. конфликт с существующим файлом: старое имя возвращается, оба файла целы;
9. переименование «только регистр» разрешено;
10. переименование открытой картинки обновляет имя в статусе просмотра;
11. смоук: версия 0.8.4.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_rename.py
"""

import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit

from app import __version__  # noqa: E402
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


def load_wait(viewer, app, folder: str) -> None:
    """Открыть папку и ДОЖДАТЬСЯ фонового скана (см. test_delete_restore)."""
    expected = len([n for n in os.listdir(folder)
                    if n.lower().endswith(".png")])
    viewer.load_folder(folder)
    wait_until(app, lambda: viewer.list.count() == expected,
               timeout_s=10.0)
    # раскладке ленты (ResizeMode.Adjust) нужен ещё один оборот событий,
    # иначе visualItemRect возвращает прямоугольник до пересчёта сетки
    for _ in range(50):
        app.processEvents()


def make_png(path: str) -> None:
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(0xFF00FF00)
    assert img.save(path)


def dblclick(widget, x: float, y: float) -> None:
    """Нажатие + двойной клик по виджету в его координатах (offscreen).

    События отправляются на viewport честной доставкой (QApplication.sendEvent):
    QAbstractScrollArea перехватывает события вьюпорта и передаёт их
    mouseDoubleClickEvent самого представления — как при настоящей мышке.
    Нажатие обязательно: представление обрабатывает двойной клик только на
    той плитке, на которой был зафиксирован pressedIndex."""
    for ev_type in (QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonDblClick):
        ev = QMouseEvent(ev_type, QPointF(x, y), QPointF(x, y),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, ev)


def commit_editor(viewer, item, new_text: str) -> None:
    """Завершить правку имени так же, как это делает представление."""
    eds = viewer.list.findChildren(QLineEdit)
    assert eds, "редактор имени не открыт"
    ed = eds[0]
    ed.setText(new_text)
    idx = viewer.list.indexFromItem(item)
    viewer.list.itemDelegate().setModelData(ed, viewer.list.model(), idx)


class _Loc:
    HomeLocation = 0
    PicturesLocation = 1
    GenericCacheLocation = 2


class FakeStdPaths:
    StandardLocation = _Loc

    @staticmethod
    def writableLocation(_kind) -> str:
        return tempfile.mkdtemp(prefix="ih_ren_home_")


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


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ih_ren_")

    lv.QStandardPaths = FakeStdPaths
    lv.QStorageInfo = types.SimpleNamespace(mountedVolumes=lambda: [FakeSI(tmp)])

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    i18n.set_lang("ru", persist=False)

    # открытие файлов по двойному клику подменяем записывающей заглушкой:
    # в offscreen-среде реальный просмотрщик не нужен
    opened: list[str] = []
    lv.QDesktopServices = types.SimpleNamespace(
        openUrl=lambda url: opened.append(url.toString()))

    viewer = LocalViewer()
    viewer.resize(900, 700)
    viewer.show()
    app.processEvents()

    # ---------- 1. чистка и проверка имени ----------
    check("чистка: пробелы по краям",
          lv._clean_rename_name("  кот.png  ") == "кот.png",
          repr(lv._clean_rename_name("  кот.png  ")))
    check("чистка: точки на конце",
          lv._clean_rename_name("кот.png...") == "кот.png",
          repr(lv._clean_rename_name("кот.png...")))
    check("чистка: имя без имени («...») пустеет",
          lv._clean_rename_name("...") == "")
    check("чистка: «.gitignore» не тронут",
          lv._clean_rename_name(".gitignore") == ".gitignore")
    check("допустимо: обычное имя", lv._name_is_allowed("кот.png"))
    check("допустимо: скрытый файл", lv._name_is_allowed(".gitignore"))
    check("отказ: пустое", not lv._name_is_allowed(""))
    check("отказ: точка", not lv._name_is_allowed("."))
    check("отказ: две точки", not lv._name_is_allowed(".."))
    check("отказ: слэш", not lv._name_is_allowed("a/b.png"))
    check("отказ: двоеточие", not lv._name_is_allowed("a:b.png"))
    check("отказ: звёздочка", not lv._name_is_allowed("a*.png"))
    check("отказ: кавычка", not lv._name_is_allowed('a"b.png'))
    check("отказ: уголок", not lv._name_is_allowed("a<b>.png"))
    check("отказ: труба", not lv._name_is_allowed("a|b.png"))
    check("отказ: вопрос", not lv._name_is_allowed("a?b.png"))
    check("отказ: управляющий символ", not lv._name_is_allowed("a\x01b.png"))
    check("допустимо: пробел внутри", lv._name_is_allowed("кот и пёс.png"))

    # ---------- 2. пункт меню и F2 ----------
    menu, acts = viewer._build_list_menu()
    texts = [a.text() for a in menu.actions()]
    check("меню: «Переименовать» есть",
          i18n.tr("viewer.ctx_rename") in texts, str(texts))
    check("меню: ключ rename в acts", "rename" in acts, str(list(acts)))
    check("меню: подсказка пункта",
          acts["rename"].toolTip() == i18n.tr("viewer.ctx_rename_tip"))
    f2_seq = QKeySequence("F2")
    scs = viewer.list.findChildren(QShortcut)
    check("шорткат F2 на списке есть",
          any(sc.key().matches(f2_seq) == QKeySequence.SequenceMatch.ExactMatch
              for sc in scs),
          str([sc.key().toString() for sc in scs]))

    # ---------- 3. геометрия подписи плитки ----------
    make_png(os.path.join(tmp, "cat_photo.jpg"))
    load_wait(viewer, app, tmp)
    item = viewer.list.item(0)
    r = viewer.list.visualItemRect(item)
    icon_h = viewer.list.iconSize().height()
    on_icon = QPointF(r.x() + r.width() // 2, r.top() + icon_h // 2)
    on_name = QPointF(r.x() + r.width() // 2, r.bottom() - 3)
    check("клик по центру иконки — не имя",
          not viewer.list._pos_on_name(item, on_icon.toPoint()))
    check("клик по нижней полосе — имя",
          viewer.list._pos_on_name(item, on_name.toPoint()),
          f"rect={r} point={on_name.toPoint()}")
    check("клик мимо плитки — не имя",
          not viewer.list._pos_on_name(item, QPoint(r.right() + 40, r.bottom() - 3)))

    # ---------- 4. маршрутизация двойного клика ----------
    named: list = []
    viewer.list.nameDoubleClicked.connect(lambda it: named.append(it))
    dblclick(viewer.list.viewport(), on_name.x(), on_name.y())
    app.processEvents()
    check("двойной клик по имени → редактор открыт",
          bool(viewer.list.findChildren(QLineEdit)), str(named))
    check("двойной клик по имени: файл НЕ открывался", not opened, str(opened))
    # Esc — редактор закрывается, имя не менялось
    ed = viewer.list.findChildren(QLineEdit)[0]
    esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                    Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(ed, esc)
    app.processEvents()
    wait_until(app, lambda: not viewer.list.findChildren(QLineEdit))
    check("Esc закрывает редактор, имя прежнее",
          not viewer.list.findChildren(QLineEdit)
          and viewer.list.item(0).text() == "cat_photo.jpg"
          and os.path.exists(os.path.join(tmp, "cat_photo.jpg")))

    dblclick(viewer.list.viewport(), on_icon.x(), on_icon.y())
    app.processEvents()
    check("двойной клик по картинке → файл открывается",
          len(opened) == 1 and opened[0].endswith("cat_photo.jpg"), str(opened))
    check("двойной клик по картинке: редактор не открыт",
          not viewer.list.findChildren(QLineEdit))
    # ---------- 5. полный цикл: правка имени и Enter ----------
    item = viewer.list.item(0)
    viewer._begin_rename(item)
    app.processEvents()
    ed = viewer.list.findChildren(QLineEdit)[0] if viewer.list.findChildren(QLineEdit) else None
    check("редактор открыт по _begin_rename", ed is not None)
    if ed is not None:
        check("выделено имя без расширения",
              ed.selectedText() == "cat_photo",
              f"sel={ed.selectedText()!r} text={ed.text()!r}")
    wait_until(app, lambda: viewer._pixmap is not None or viewer._movie is not None)
    commit_editor(viewer, item, "новый_кот.png")
    wait_until(app, lambda: not viewer._rename_inflight)
    check("файл переименован на диске",
          os.path.exists(os.path.join(tmp, "новый_кот.png"))
          and not os.path.exists(os.path.join(tmp, "cat_photo.jpg")))
    check("путь в _paths обновлён",
          viewer._paths[0] == os.path.join(tmp, "новый_кот.png"),
          str(viewer._paths))
    check("плитка: текст и путь",
          viewer.list.item(0).text() == "новый_кот.png"
          and viewer.list.item(0).data(Qt.UserRole)
          == os.path.join(tmp, "новый_кот.png"))
    check("статус: «Переименовано: … → …»",
          viewer.status.text() == i18n.tr("viewer.rename_done",
                                          old="cat_photo.jpg", new="новый_кот.png"),
          viewer.status.text())
    check("флаг переименования снят", not viewer._rename_inflight)

    # ---------- 6. отказ: пустое имя и запрещённые символы ----------
    item = viewer.list.item(0)
    item.setText("   ")
    app.processEvents()
    check("пустое имя отклонено, текст возвращён",
          viewer.list.item(0).text() == "новый_кот.png"
          and not viewer._rename_inflight
          and os.path.exists(os.path.join(tmp, "новый_кот.png")),
          viewer.list.item(0).text())
    check("статус: имя не подходит",
          viewer.status.text() == i18n.tr("viewer.rename_invalid"),
          viewer.status.text())
    item.setText("плохое<имя.png")
    app.processEvents()
    check("запрещённый символ отклонён",
          viewer.list.item(0).text() == "новый_кот.png"
          and not os.path.exists(os.path.join(tmp, "плохое<имя.png")))
    item.setText("новый_кот.png")   # то же имя — ничего не происходит
    app.processEvents()
    check("то же имя — тихий no-op", not viewer._rename_inflight)
    item.setText("новый_кот.png   ")   # то же имя с хвостом — приводится
    app.processEvents()
    check("хвостовые пробелы свернулись к тому же имени",
          viewer.list.item(0).text() == "новый_кот.png"
          and not viewer._rename_inflight)

    # ---------- 7. конфликт с существующим файлом ----------
    # порядок плиток не лексикографический (кириллица после латиницы) —
    # плитку ищем по пути, а не по номеру строки
    make_png(os.path.join(tmp, "second.png"))
    load_wait(viewer, app, tmp)   # новый_кот.png, second.png
    check("в папке 2 файла", viewer.list.count() == 2, str(viewer.list.count()))
    # Ошибка конфликта ставится в статус внутри _on_rename_done, но фоновая
    # загрузка миниатюры может перекрыть её в той же пачке событий — наблюдаем
    # сам сигнал done(ok=False): детерминировано при любой гонке статуса
    seen_err: list[str] = []
    def _probe(old_p, new_p, ok, err):
        if not ok:
            seen_err.append(err)
    viewer._rename_signals.done.connect(_probe)
    item = viewer._item_by_path(os.path.join(tmp, "новый_кот.png"))
    check("плитка нового_кот.png найдена по пути", item is not None)
    item.setText("second.png")
    wait_until(app, lambda: not viewer._rename_inflight)
    check("конфликт: старое имя возвращено в плитку",
          item.text() == "новый_кот.png"
          and item.data(Qt.UserRole) == os.path.join(tmp, "новый_кот.png"),
          item.text())
    check("конфликт: оба файла целы",
          os.path.exists(os.path.join(tmp, "новый_кот.png"))
          and os.path.exists(os.path.join(tmp, "second.png")))
    check("конфликт: _paths без изменений",
          os.path.join(tmp, "новый_кот.png") in viewer._paths
          and os.path.join(tmp, "second.png") in viewer._paths,
          str(viewer._paths))
    # статус ставится сигналом из рабочего потока: он мог прийти на тик позже
    # исчезновения _rename_inflight — ждём его, а не читаем сразу (гонка)
    check("конфликт: статус с ошибкой",
          seen_err and "second.png" in seen_err[0],
          str(seen_err) + " | статус: " + viewer.status.text())
    try:
        viewer._rename_signals.done.disconnect(_probe)
    except (RuntimeError, TypeError):
        pass

    # ---------- 8. переименование «только регистр» ----------
    item = viewer._item_by_path(os.path.join(tmp, "новый_кот.png"))
    item.setText("НОВЫЙ_КОТ.PNG")
    wait_until(app, lambda: not viewer._rename_inflight)
    check("регистр изменён на диске",
          os.path.exists(os.path.join(tmp, "НОВЫЙ_КОТ.PNG"))
          and not os.path.exists(os.path.join(tmp, "новый_кот.png")),
          str(os.listdir(tmp)))
    check("путь в _paths с новым регистром",
          os.path.join(tmp, "НОВЫЙ_КОТ.PNG") in viewer._paths,
          str(viewer._paths))

    # ---------- 9. открытая картинка: имя в статусе просмотра ----------
    load_wait(viewer, app, tmp)
    wait_until(app, lambda: viewer._pixmap is not None or viewer._movie is not None)
    cur_row = viewer.list.currentRow()
    cur_path = viewer._paths[cur_row]
    cur_name = os.path.basename(cur_path)
    before = viewer.status.text()
    check("статус просмотра показывает имя открытой картинки",
          cur_name in before, f"{cur_name!r} в {before!r}")
    item = viewer.list.currentItem()
    item.setText("открытая.png")
    wait_until(app, lambda: not viewer._rename_inflight)
    check("статус просмотра обновил имя",
          "открытая.png" in viewer.status.text(), viewer.status.text())
    check("картинка в просмотре осталась (пиксмап на месте)",
          viewer._pixmap is not None and not viewer._pixmap.isNull())

    # ---------- 10. повторная правка после конфликта ----------
    item = viewer._item_by_path(cur_path)
    check("плитка открытой картинки найдена после переименования", item is None)
    item = viewer.list.currentItem()
    viewer._begin_rename(item)
    app.processEvents()
    eds = viewer.list.findChildren(QLineEdit)
    check("редактор снова открывается после ошибок", bool(eds))
    if eds:
        commit_editor(viewer, item, "финал.png")
        wait_until(app, lambda: not viewer._rename_inflight)
        check("финальное переименование удалось",
              os.path.exists(os.path.join(tmp, "финал.png"))
              and viewer.list.currentItem().text() == "финал.png")

    # ---------- 11. смоук ----------
    check("версия 0.8.4", __version__ == "0.8.4", __version__)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
