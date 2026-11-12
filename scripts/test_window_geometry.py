"""Геометрия главного окна запоминается между запусками (v0.8.23).

Проверяется: при первом запуске (записи нет) окно стартует со штатных
1280×820; закрытие пишет в QSettings ключ window/geometry (байты, родной
формат saveGeometry); новое окно применяет сохранённую геометрию (в
offscreen-экране 800×800 пиксельно точный размер MainWindow не проверить —
минимум 960×600 шире экрана и Qt честно сжимает окно под экран, поэтому
точный round-trip размера и позиции проверяется теми же методами
_save/_restore_window_geometry на виджете, влезающем в экран); развёрнутое
(maximized) состояние восстанавливается; битая запись (строка вместо
байтов) и мусорные байты пропускаются без падения — окно стартует
с 1280×820; ключ подчищается за собой.

Запуск: QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" \
        python scripts/test_window_geometry.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def geom_str(w) -> str:
    g = w.frameGeometry()
    return f"({g.x()},{g.y()}) {g.width()}x{g.height()}"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    st.setValue("viewer/last_query", "")
    st.setValue("web/tabs", "")
    st.remove("window/geometry")   # старт всегда с чистого листа
    st.sync()

    check("версия 0.8.26", __version__ == "0.8.26", __version__)

    # --- первый запуск: записи нет — окно со штатными 1280×820 ---
    win0 = MainWindow()
    check("первый запуск: ширина 1280", win0.width() == 1280, str(win0.width()))
    check("первый запуск: высота 820", win0.height() == 820, str(win0.height()))
    win0.show()
    app.processEvents()
    win0.close()
    app.processEvents()

    # --- закрытие записывает window/geometry ---
    saved = st.value("window/geometry")
    check("после закрытия ключ window/geometry есть", saved is not None,
          repr(saved)[:60])
    check("запись — байты, а не строка",
          saved is not None and not isinstance(saved, str),
          type(saved).__name__ if saved is not None else "None")
    check("запись непустая", saved is not None and len(saved) > 0,
          str(len(saved)) if saved is not None else "0")

    # --- новый запуск: сохранённая геометрия применилась ---
    win1 = MainWindow()
    win1.show()
    app.processEvents()
    win1.resize(1152, 736)   # ≥ минимума 960×600
    win1.move(40, 30)
    app.processEvents()
    win1.close()
    app.processEvents()

    win2 = MainWindow()
    win2.show()
    app.processEvents()
    # примечание: экран offscreen — 800×800, а минимум окна 960×600, шире
    # экрана; Qt честно сжимает окно под экран (на рабочем столе то же
    # поведение для окна, брошенного на отключённый монитор), поэтому
    # пиксельно точный размер не проверяем — только что restore применился:
    # ширина стала 960 (минимум, место дефолта 1280), не 1280
    check("restore применился: ширина не дефолтная", win2.width() != 1280,
          str(win2.width()))
    check("высота вернулась точной", win2.frameGeometry().height() == 740,
          str(win2.frameGeometry().height()))   # 736 клиента + 2×2 рамки
    check("окно не развёрнуто", not win2.isMaximized())
    win2.close()
    app.processEvents()

    # --- развёрнутое состояние восстанавливается ---
    win3 = MainWindow()
    win3.showMaximized()
    app.processEvents()
    check("showMaximized сработал в offscreen", win3.isMaximized())
    win3.close()
    app.processEvents()

    win4 = MainWindow()
    check("новое окно сразу maximized", win4.isMaximized(),
          str(win4.windowState()))
    win4.show()
    app.processEvents()
    check("после показа всё ещё maximized", win4.isMaximized())
    win4.close()
    app.processEvents()

    # --- точный round-trip размера и позиции ---
    # Сами методы не зависят от QMainWindow: внутри только saveGeometry/
    # restoreGeometry + QSettings, так что проверяем их на виджете,
    # влезающем в offscreen-экран (MainWindow минимум 960×600 туда не
    # влезает — см. примечание выше). Полный путь окна покрывают шаги с
    # maximized и мусорными записями.
    probe = QWidget()
    probe.show()
    app.processEvents()
    probe.resize(700, 650)
    probe.move(30, 40)
    app.processEvents()
    MainWindow._save_window_geometry(probe)
    ref = probe.frameGeometry()
    saved = QSettings("ImageHunter", "ImageHunter").value("window/geometry")
    check("сохранение метода окна — байты", saved is not None
          and not isinstance(saved, str) and len(saved) > 0,
          type(saved).__name__ if saved is not None else "None")

    probe2 = QWidget()
    probe2.show()
    app.processEvents()
    MainWindow._restore_window_geometry(probe2)
    app.processEvents()
    check("размер вернулся точный",
          (probe2.frameGeometry().width(), probe2.frameGeometry().height())
          == (ref.width(), ref.height()),
          f"{probe2.frameGeometry().width()}x{probe2.frameGeometry().height()}"
          f" vs {ref.width()}x{ref.height()}")
    check("позиция вернулась точная",
          (probe2.x(), probe2.y()) == (ref.x(), ref.y()),
          f"({probe2.x()},{probe2.y()}) vs ({ref.x()},{ref.y()})")

    # --- битая запись (строка вместо байтов) пропускается ---
    st.setValue("window/geometry", "мусор-из-ini")
    st.sync()
    win5 = MainWindow()
    check("строка в настройках: окно 1280×820, не падаем",
          (win5.width(), win5.height()) == (1280, 820), geom_str(win5))
    check("строка в настройках: не maximized", not win5.isMaximized())
    win5.close()
    app.processEvents()

    # --- мусорные байты тоже пропускаются ---
    st.setValue("window/geometry", b"\x00\x01garbage")
    st.sync()
    win6 = MainWindow()
    check("мусорные байты: окно 1280×820, не падаем",
          (win6.width(), win6.height()) == (1280, 820), geom_str(win6))
    win6.close()
    app.processEvents()
    check("после закрытия настройка снова честная",
          not isinstance(st.value("window/geometry"), str))

    # --- уборка: ключ подчищен, соседние наборы стартуют с чистого листа ---
    st.remove("window/geometry")
    st.sync()
    check("уборка: ключ удалён",
          st.value("window/geometry") is None)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
