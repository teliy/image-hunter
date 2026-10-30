"""Оффлайн-тест: поле поиска в «Мои картинки» меняет ширину мышью.

Проверяет:
1) поле поиска — _GripEdit, ширина по умолчанию 220;
2) перетаскивание правого края расширяет поле (220 → 370), ширина запоминается;
3) шире MAX_W (640) и уже MIN_W (170) растянуть нельзя;
4) левый край тоже работает (тянем влево — поле растёт);
5) курсор у краёв — «↔» (SizeHor), в середине — текстовый (IBeam);
6) нажатие в середине поля не меняет ширину, набор текста работает;
7) в новом экземпляре ширина восстанавливается из настроек;
8) подсказка в тултипе упоминает растягивание (ru/en, живая перетрансляция).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_search_width.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import i18n  # noqa: E402
from app.ui import local_viewer as lv  # noqa: E402

FAILURES: list[str] = []


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


def send_mouse(w, ev_type, local: QPointF, gpos: QPointF,
               button, buttons) -> None:
    ev = QMouseEvent(ev_type, local, gpos, button, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w, ev)


def drag_edge(w, press_local_x: int, dx_total: int, steps: int = 4) -> None:
    """Зажать мышь в точке (press_local_x, середина) и протянуть на dx_total px."""
    y = w.height() / 2
    g0 = w.mapToGlobal(QPoint(int(press_local_x), int(y)))
    send_mouse(w, QEvent.Type.MouseButtonPress,
               QPointF(press_local_x, y), QPointF(g0),
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    for i in range(1, steps + 1):
        gx = g0.x() + dx_total * i / steps
        local = QPointF(w.mapFromGlobal(QPoint(int(round(gx)), int(g0.y()))))
        send_mouse(w, QEvent.Type.MouseMove, local, QPointF(gx, g0.y()),
                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    local = QPointF(w.mapFromGlobal(QPoint(int(round(g0.x() + dx_total)), int(g0.y()))))
    send_mouse(w, QEvent.Type.MouseButtonRelease, local,
               QPointF(g0.x() + dx_total, g0.y()),
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)


def hover(w, local_x: float) -> None:
    y = w.height() / 2
    g = w.mapToGlobal(QPoint(int(local_x), int(y)))
    send_mouse(w, QEvent.Type.MouseMove, QPointF(local_x, y), QPointF(g),
               Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru")
    st = QSettings("ImageHunter", "ImageHunter")
    st.remove("viewer/search_width")   # детерминизм
    st.remove("viewer/splitter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")

    try:
        viewer = lv.LocalViewer()
        viewer.resize(1400, 800)
        viewer.show()
        pump(app, 300)
        e = viewer.search_edit

        # --- 1. класс и ширина по умолчанию ---
        check("поле поиска — _GripEdit", isinstance(e, lv._GripEdit))
        check("ширина по умолчанию 220", e.width() == 220, f"width={e.width()}")

        # --- 2. тянем правый край ---
        drag_edge(e, e.width() - 2, +150)
        check("правый край: поле расширилось 220 → 370", e.width() == 370,
              f"width={e.width()}")
        check("ширина запомнена в настройках",
              int(st.value("viewer/search_width", 0, int)) == 370,
              str(st.value("viewer/search_width")))

        # --- 3. пределы ширины ---
        drag_edge(e, e.width() - 2, +5000)
        check("шире MAX_W (640) не растянуть", e.width() == lv._GripEdit.MAX_W,
              f"width={e.width()}")
        drag_edge(e, e.width() - 2, -5000)
        check("уже MIN_W (170) не сузить", e.width() == lv._GripEdit.MIN_W,
              f"width={e.width()}")

        # --- 4. левый край: тянем влево — поле растёт ---
        drag_edge(e, 1, -60)
        check("левый край: тянем влево, поле растёт 170 → 230", e.width() == 230,
              f"width={e.width()}")

        # --- 5. курсор-подсказка у краёв ---
        hover(e, e.width() / 2)
        check("в середине курсор текстовый (IBeam)",
              e.cursor().shape() == Qt.CursorShape.IBeamCursor)
        hover(e, 2)
        check("у левого края курсор «↔» (SizeHor)",
              e.cursor().shape() == Qt.CursorShape.SizeHorCursor)
        hover(e, e.width() - 2)
        check("у правого края курсор «↔» (SizeHor)",
              e.cursor().shape() == Qt.CursorShape.SizeHorCursor)
        hover(e, e.width() / 2)
        check("снова в середине — IBeam",
              e.cursor().shape() == Qt.CursorShape.IBeamCursor)

        # --- 6. нажатие в середине не тянет край, текст вводится ---
        w_before = e.width()
        mid = e.width() / 2
        g_mid = e.mapToGlobal(QPoint(int(mid), int(e.height() / 2)))
        send_mouse(e, QEvent.Type.MouseButtonPress, QPointF(mid, e.height() / 2),
                   QPointF(g_mid), Qt.MouseButton.LeftButton,
                   Qt.MouseButton.LeftButton)
        send_mouse(e, QEvent.Type.MouseButtonRelease, QPointF(mid, e.height() / 2),
                   QPointF(g_mid), Qt.MouseButton.LeftButton,
                   Qt.MouseButton.NoButton)
        check("нажатие в середине не меняет ширину", e.width() == w_before,
              f"{w_before} → {e.width()}")
        e.setFocus()
        from PySide6.QtTest import QTest
        QTest.keyClicks(e, "cat")
        check("набор текста работает как раньше", e.text() == "cat",
              f"text={e.text()!r}")
        e.clear()

        # --- 7. ширина восстанавливается в новом экземпляре ---
        viewer2 = lv.LocalViewer()
        viewer2.resize(1400, 800)
        viewer2.show()
        pump(app, 300)
        check("в новом экземпляре ширина восстановлена (230)",
              viewer2.search_edit.width() == 230,
              f"width={viewer2.search_edit.width()}")

        # --- 8. тултип упоминает растягивание, en/ru переключаются живьём ---
        check("подсказка про растягивание (ru)",
              "потяните" in viewer2.search_edit.toolTip().lower())
        i18n.set_lang("en")
        check("подсказка про растягивание (en)",
              "drag" in viewer2.search_edit.toolTip().lower())
        i18n.set_lang("ru")

        st.remove("viewer/search_width")
        st.remove("viewer/splitter")
    finally:
        st.remove("viewer/search_width")
        st.remove("viewer/splitter")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
