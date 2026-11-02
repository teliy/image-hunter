"""Оффлайн-тест «текущее задание — внизу, в статусной строке» (v0.7.13).

Журнал — полная хроника, но вкладку ещё надо открыть; каждая строка
журнала (INFO и выше) теперь дублируется в левую часть статус-бара.

Проверяет:
1. сразу после запуска внизу «Готово» — события сборки окна не затирают его;
2. событие журнала (applog.event, ключ i18n) появляется в статус-баре;
3. обычные записи applog.info/warning/error тоже дублируются;
4. DEBUG не показывается — технический шум;
5. многострочная запись (трассировка) — только первая строка, включая
   случай, когда первая строка пустая;
6. слишком длинная строка обрезается до 220 символов с «…»;
7. запись из рабочего потока доезжает до статус-бара (queued-сигнал),
   без суффикса имени потока и без времени;
8. журнал (LogView) не сломан — строки по-прежнему попадают и туда;
9. сообщение без таймаута: следующее событие заменяет предыдущее, а само
   оно висит, пока программа молчит (текущее задание видно постоянно).

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_status_log.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import applog, i18n  # noqa: E402

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


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", "")
    applog.setup()

    from app.ui.main_window import MainWindow

    win = MainWindow()

    # 1. стартовое «Готово» не затёрто событиями сборки окна: подписка на
    #    мост устанавливается ПОСЛЕ showMessage(main.ready)
    check("после запуска внизу «Готово»",
          win._status.currentMessage() == i18n.tr("main.ready"),
          win._status.currentMessage())

    pump(app, 300)

    # 2. событие журнала (i18n-ключ) — в статус-баре
    want = i18n.tr("log.event.search_done", q="кот", n=3)
    applog.event("log.event.search_done", q="кот", n=3)
    pump(app, 200)
    check("событие журнала видно внизу (язык интерфейса)",
          win._status.currentMessage() == want,
          win._status.currentMessage())

    # 3. обычные записи info/warning/error — тоже
    applog.info("СТАТУС_ИНФО")
    pump(app, 100)
    check("applog.info дублируется внизу",
          win._status.currentMessage() == "СТАТУС_ИНФО",
          win._status.currentMessage())
    applog.warning("СТАТУС_ПРЕДУПРЕЖДЕНИЕ")
    pump(app, 100)
    check("applog.warning дублируется внизу",
          win._status.currentMessage() == "СТАТУС_ПРЕДУПРЕЖДЕНИЕ",
          win._status.currentMessage())
    applog.error("СТАТУС_ОШИБКА")
    pump(app, 100)
    check("applog.error дублируется внизу",
          win._status.currentMessage() == "СТАТУС_ОШИБКА",
          win._status.currentMessage())

    # 4. DEBUG — не показываем
    applog.debug("DEBUG_СКРЫТОЕ_СООБЩЕНИЕ")
    pump(app, 100)
    check("DEBUG не попадает в статус-бар",
          win._status.currentMessage() == "СТАТУС_ОШИБКА",
          win._status.currentMessage())

    # 5. многострочная запись — только первая строка
    applog.error("Необработанное исключение: ValueError\nTraceback (most recent):\n  line 1")
    pump(app, 100)
    check("трассировка показана первой строкой",
          win._status.currentMessage() == "Необработанное исключение: ValueError",
          win._status.currentMessage())
    applog.error("\n\nвторая строка после пустых")
    pump(app, 100)
    check("первое непустое берётся, если заголовок пуст",
          win._status.currentMessage() == "вторая строка после пустых",
          win._status.currentMessage())

    # 6. длинная строка обрезается до 220 с «…»
    applog.info("Д" * 400)
    pump(app, 100)
    cur = win._status.currentMessage()
    check("длинная строка обрезана",
          len(cur) == MainWindow.LOG_STATUS_MAX and cur.endswith("…")
          and cur.count("Д") == MainWindow.LOG_STATUS_MAX - 1,
          f"len={len(cur)}")

    # 7. запись из рабочего потока: доезжает, чистый текст без времени/потока
    holder: list[str] = []
    def worker() -> None:
        applog.info("ИЗ_РАБОЧЕГО_ПОТОКА")
    t = threading.Thread(target=worker, name="TestWorker-7")
    t.start()
    t.join()
    pump(app, 400)
    holder.append(win._status.currentMessage())
    check("событие из рабочего потока видно внизу",
          holder[-1] == "ИЗ_РАБОЧЕГО_ПОТОКА", holder[-1])

    # 8. журнал при этом не сломан: строка с меткой потока — там, в журнале
    log_text = win.log_view.text.toPlainText()
    check("журнал по-прежнему принимает строки",
          "ИЗ_РАБОЧЕГО_ПОТОКА" in log_text and "TestWorker-7" in log_text,
          log_text[-120:].replace("\n", " | "))

    # 9. сообщение держится без таймаута, пока программа молчит
    time.sleep(0.6)
    app.processEvents()
    check("сообщение не гаснет без таймаута",
          win._status.currentMessage() == "ИЗ_РАБОЧЕГО_ПОТОКА",
          win._status.currentMessage())

    win.close()
    print()
    if FAILURES:
        print(f"ПРОВАЛОВ: {len(FAILURES)}")
        return 1
    print("Все проверки зелёные")
    return 0


if __name__ == "__main__":
    sys.exit(main())
