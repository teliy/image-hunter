"""Оффлайн-тест чекбокса «игнорировать дефис» в поиске по имени.

Если галочка включена, запрос «23542-23523» находит и «2354223523» —
дефисы не различаются ни в запросе, ни в именах файлов.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_ignore_dash.py
"""

import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import applog, i18n  # noqa: E402
from app.core.i18n import tr  # noqa: E402
from app.ui import local_viewer as lv  # noqa: E402
from app.ui.local_viewer import LocalViewer  # noqa: E402
from app.ui.log_view import LogView  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def make_image(path: str) -> None:
    img = QImage(24, 24, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    assert img.save(path)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    applog.setup()   # мост logging→Qt: без него записи не доходят до журнала
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/search_ignore_dash", False)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", True)
    QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", "")

    tmp = tempfile.mkdtemp(prefix="ih_dash_")
    make_image(os.path.join(tmp, "2354223523.png"))    # без дефиса
    make_image(os.path.join(tmp, "23542-23523.png"))   # с дефисом
    make_image(os.path.join(tmp, "AB-12-34.png"))      # несколько дефисов
    make_image(os.path.join(tmp, "other.png"))

    viewer = LocalViewer()
    viewer.load_folder(tmp)
    app.processEvents()

    def wait_until(cond, timeout_s: float = 10.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            app.processEvents()
            if cond():
                time.sleep(0.08)   # хвост: дать прийти завершающему сигналу
                app.processEvents()
                return True
            time.sleep(0.02)
        return False

    try:
        # 1. по умолчанию галочка выключена
        check("чекбокс по умолчанию выключен", not viewer.ignore_dash_box.isChecked())

        # 2. без галочки: запрос с дефисом находит только файл с дефисом
        viewer.search_edit.setText("23542-23523")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer._search_handle is None
                        and viewer.list.count() == 1)
        check("без галочки «23542-23523» находит 1 файл", ok,
              f"count={viewer.list.count()}")
        names = [viewer.list.item(i).text() for i in range(viewer.list.count())]
        check("и это именно файл с дефисом", names == ["23542-23523.png"], str(names))

        # 3. включили галочку — поиск перезапустился сам и нашёл оба файла
        viewer.ignore_dash_box.setChecked(True)
        ok = wait_until(lambda: viewer._search_handle is None
                        and viewer.list.count() == 2)
        check("галочка включена: «23542-23523» находит оба файла", ok,
              f"count={viewer.list.count()}")

        # 4. запрос без дефиса тоже находит оба
        viewer.search_edit.setText("2354223523")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer._search_handle is None
                        and viewer.list.count() == 2)
        check("запрос без дефиса находит оба файла", ok,
              f"count={viewer.list.count()}")

        # 5. несколько дефисов и регистр: «ab1234» находит «AB-12-34.png»
        viewer.search_edit.setText("ab1234")
        viewer._start_search_now()
        ok = wait_until(lambda: viewer._search_handle is None
                        and viewer.list.count() == 1)
        check("несколько дефисов тоже игнорируются", ok,
              f"count={viewer.list.count()}")

        # 6. выключили галочку — то же имя больше не находится
        viewer.ignore_dash_box.setChecked(False)
        ok = wait_until(lambda: viewer._search_handle is None
                        and viewer.list.count() == 0)
        check("галочка выключена: «ab1234» не находит «AB-12-34»", ok,
              f"count={viewer.list.count()}")

        # 7. настройка запоминается в QSettings
        st = QSettings("ImageHunter", "ImageHunter")
        check("QSettings помнит выключенное состояние",
              st.value("viewer/search_ignore_dash", False, type=bool) is False)
        viewer.ignore_dash_box.setChecked(True)
        check("QSettings помнит включённое состояние",
              st.value("viewer/search_ignore_dash", False, type=bool) is True)

        # 8. переключение при пустом поле: не ищем и не падаем
        viewer.search_edit.clear()
        app.processEvents()
        before = viewer.list.count()
        viewer.ignore_dash_box.setChecked(False)
        app.processEvents()
        check("пустое поле: переключение не запускает поиск",
              viewer._search_handle is None and viewer.list.count() == before)

        # 9. юнит: _SearchTask напрямую, обе галочки
        sig = lv._SearchSignals()
        batches: list[list] = []
        dones: list[tuple[int, bool]] = []
        sig.batch.connect(lambda g, items: batches.append(list(items)))
        sig.done.connect(lambda g, total, trunc: dones.append((total, trunc)))

        t1 = lv._SearchTask(tmp, "23542-23523".lower(), 1, sig,
                            lv._SearchHandle(), ignore_dash=True)
        t1.run()
        flat = [p for b in batches for p in b]
        check("юнит: ignore_dash=True нашёл оба файла",
              dones and dones[0][0] == 2 and len(flat) == 2, f"{dones}")
        batches.clear()
        dones.clear()
        t2 = lv._SearchTask(tmp, "23542-23523".lower(), 2, sig,
                            lv._SearchHandle(), ignore_dash=False)
        t2.run()
        flat2 = [p for b in batches for p in b]
        check("юнит: ignore_dash=False нашёл только файл с дефисом",
              dones and dones[0][0] == 1 and len(flat2) == 1
              and os.path.basename(flat2[0][0]) == "23542-23523.png", f"{dones}")

        # 10. журнал: ошибки сохранения/скачивания видны (формат + доставка)
        log_view = LogView()
        log_view.show()
        applog.error(tr("log.event.save_file_err",
                        url="http://x/bad.png", err="не изображение (text/html)"))
        applog.error(tr("log.event.dl_file_err",
                        url="http://x/dl.png", err="404"))
        deadline = time.time() + 3
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        text = log_view.text.toPlainText()
        check("ошибка сохранения видна в журнале (ссылка + причина)",
              "http://x/bad.png" in text and "не изображение" in text, text[-160:])
        check("ошибка скачивания видна в журнале",
              "http://x/dl.png" in text and "404" in text, text[-160:])

        # 11. новые i18n-ключи есть во всех трёх языках
        for key in ("viewer.ignore_dash", "viewer.ignore_dash_tip",
                    "log.event.save_file_err", "log.event.dl_file_err"):
            langs = i18n._STRINGS.get(key, {})
            check(f"i18n {key}: ru/en/zh",
                  all(langs.get(l) for l in ("ru", "en", "zh")), str(sorted(langs)))
        check("подсказка чекбокса упоминает артикул",
              "23542-23523" in tr("viewer.ignore_dash_tip"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
