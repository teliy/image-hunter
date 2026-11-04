"""Оффлайн-тест меню «Модули» (v0.8.2).

Меню стоит в строке меню слева от «Справки» и собирается заново при
каждом открывании. Проверяется:

1. порядок меню: «Модули» → «Справка»;
2. раздел rembg: заголовок-состояние, установка/удаление по факту,
   подменю модели с галочкой; выбор модели сохраняется;
3. раздел веб-сервера: заголовок-состояние, запуск/остановка,
   автостарт (галочка пишет настройку и журнал), панель;
4. ленивость: открытие меню не импортирует app.server;
5. пункты установки/удаления/модели ушли из контекстного меню ленты;
6. перетрансляция заголовка при смене языка.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_modules_menu.py
"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n  # noqa: E402
from app.ui import rembg_manager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def wait_until(cond, timeout_s: float = 15.0) -> bool:
    """Крутить цикл событий до условия (фоновая задача не ждёт один
    processEvents — исторический флейм песочницы, приём test_tree)."""
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def actions_of(menu):
    """Пункты меню после пересборки (aboutToShow тесты зовёт напрямую)."""
    menu._rebuild()
    return list(menu.actions())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)

    # чистые настройки: автостарт выключен, порт — свободный
    st = QSettings("ImageHunter", "ImageHunter")
    st.setValue("server/autostart", False)
    st.setValue("server/port", free_port())
    st.setValue("viewer/thumbs", True)
    st.setValue("viewer/last_folder", "")
    st.setValue("web/tabs", "")

    win = MainWindow()
    win.show()
    app.processEvents()

    check("версия 0.8.3", __version__ == "0.8.3", __version__)

    # ---------- состав строки меню ----------
    top = win.menuBar().actions()
    titles = [a.text() for a in top]
    check("меню «Модули» есть в строке меню",
          i18n.tr("menu.modules") in titles, str(titles))
    check("«Модули» стоит левее «Справки»",
          len(top) >= 2 and top[-2].text() == i18n.tr("menu.modules")
          and top[-1].text() == i18n.tr("menu.help"), str(titles))
    check("кнопки 🌐 больше нет в статус-баре",
          not hasattr(win, "btn_server"))

    # ---------- ленивость: открытие меню не импортирует app.server ----------
    import app.ui.modules_menu as mm  # noqa: F401  (сам меню-модуль — можно)
    mods_before = set(sys.modules)
    win._modules_menu.popup(QPoint(20, 20))
    app.processEvents()
    win._modules_menu.close()
    app.processEvents()
    check("открытие меню не импортирует app.server",
          not any(m == "app.server" or m.startswith("app.server.")
                  for m in set(sys.modules) - mods_before))
    check("менеджер сервера ещё не создан",
          getattr(win, "_server_mgr", "no-attr") is None)

    # ---------- раздел rembg (в песочнице модуль не установлен) ----------
    acts = actions_of(win._modules_menu)
    texts = [a.text() for a in acts]
    head_r = next((a for a in acts
                   if a.text().startswith("🪄")), None)
    check("заголовок rembg: не установлен",
          head_r is not None and not head_r.isEnabled()
          and i18n.tr("modules.not_installed") in head_r.text(),
          head_r.text() if head_r else "?")
    check("пункт установки rembg на месте",
          i18n.tr("viewer.rembg_menu_install") in texts, str(texts))
    check("пункта удаления rembg нет (модуль не установлен)",
          i18n.tr("viewer.rembg_menu_uninstall") not in texts)
    m_model = next((a.menu() for a in acts
                    if a.menu() and a.text() == i18n.tr("modules.model_menu")),
                   None)
    check("подменю «Модель rembg» есть", m_model is not None)
    models = m_model.actions() if m_model else []
    check("в подменю три модели",
          len(models) == len(rembg_manager.REMBG_MODELS),
          str([a.text() for a in models]))
    check("галочка на модели по умолчанию",
          any(a.isChecked() for a in models), "")
    # выбор модели из меню: сохраняется в настройках
    models[1].trigger()
    app.processEvents()
    st.sync()
    check("выбор модели из меню сохранён",
          win.local.rembg_current_model() == rembg_manager.REMBG_MODELS[1][0]
          and st.value("viewer/rembg_model", "", type=str)
          == rembg_manager.REMBG_MODELS[1][0],
          win.local.rembg_current_model())
    st.setValue("viewer/rembg_model", "")
    win.local.rembg_set_model(rembg_manager.DEFAULT_MODEL)

    # ---------- раздел веб-сервера (менеджер ещё не создан) ----------
    head_s = next((a for a in acts if a.text().startswith("🌐")), None)
    check("заголовок сервера: остановлен",
          head_s is not None and not head_s.isEnabled()
          and i18n.tr("server.stopped", port=0)[:14] in head_s.text(),
          head_s.text() if head_s else "?")
    check("пункт «Запустить сервер» есть",
          i18n.tr("server.run") in texts, str(texts))
    act_auto = next((a for a in acts if a.text() == i18n.tr("server.autostart")),
                    None)
    check("галочка автостарта есть и снята",
          act_auto is not None and act_auto.isCheckable()
          and not act_auto.isChecked())
    check("пункт панели веб-сервера есть",
          i18n.tr("modules.panel") in texts)

    # ---------- автостарт: галочка пишет настройку и журнал ----------
    win.server_set_autostart(True)
    st.sync()
    check("автостарт записан в настройки",
          st.value("server/autostart", False, type=bool) is True)
    st.setValue("server/autostart", False)
    st.sync()
    check("автостарт выключается обратно",
          st.value("server/autostart", False, type=bool) is False)

    # ---------- запуск/остановка сервера из меню ----------
    win.server_toggle()
    app.processEvents()
    check("сервер запустился из меню", win.server_running(),
          f"port={win.server_port()}")
    check("менеджер создан лениво при действии",
          win._server_mgr is not None)
    acts = actions_of(win._modules_menu)
    texts = [a.text() for a in acts]
    check("после запуска меню предлагает остановить",
          i18n.tr("server.stop") in texts
          and i18n.tr("server.run") not in texts, str(texts))
    head_s = next((a for a in acts if a.text().startswith("🌐")), None)
    check("заголовок сервера: работает, с портом",
          head_s is not None
          and str(win.server_port()) in head_s.text(),
          head_s.text() if head_s else "?")
    win.server_toggle()
    app.processEvents()
    check("сервер остановился из меню", not win.server_running())
    acts = actions_of(win._modules_menu)
    check("после остановки меню снова предлагает запустить",
          any(a.text() == i18n.tr("server.run") for a in acts))

    # ---------- контекстное меню ленты: пункты модуля ушли ----------
    menu, lv_acts = win.local._build_list_menu()
    names = [a.text() for a in menu.actions()]
    check("в контекст-меню ленты есть «Удалить фон»",
          i18n.tr("viewer.rembg") in names, str(names))
    check("в контекст-меню нет подменю модели",
          not any(a.menu() for a in menu.actions()), str(names))
    check("в контекст-меню нет установки/удаления модуля",
          i18n.tr("viewer.rembg_menu_install") not in names
          and i18n.tr("viewer.rembg_menu_uninstall") not in names, str(names))
    check("словарь действий без inst/uninst",
          set(lv_acts) == {"open", "copy", "rename", "bg", "del"},
          str(sorted(lv_acts)))
    menu.close()

    # ---------- установка модуля из меню (pip подменён) ----------
    calls: list[list[str]] = []
    real_pip = rembg_manager._run_pip

    def fake_pip(args):
        calls.append(list(args))
        return True, ""

    rembg_manager._run_pip = fake_pip
    box_calls: list[str] = []
    real_info = QMessageBox.information
    real_warn = QMessageBox.warning
    real_quest = QMessageBox.question
    QMessageBox.information = lambda *a, **k: box_calls.append("info")
    QMessageBox.warning = lambda *a, **k: box_calls.append("warn")
    QMessageBox.question = lambda *a, **k: (
        box_calls.append("quest"), QMessageBox.StandardButton.Yes)[1]
    try:
        win.local.rembg_install()          # то же, что пункт меню
        ok = wait_until(lambda: not win.local.rembg_is_busy())
        check("установка из меню завершилась", ok)
        check("pip вызван с rembg[cpu]",
              bool(calls) and "rembg[cpu]" in calls[0], str(calls))
        check("об успехе сообщило окно",
              box_calls[-1:] == ["info"], str(box_calls))

        # меню с «установленным» модулем предлагает удаление
        real_installed = rembg_manager.is_installed
        rembg_manager.is_installed = lambda: True
        try:
            acts = actions_of(win._modules_menu)
            texts = [a.text() for a in acts]
            check("установленный модуль: пункт удаления",
                  i18n.tr("viewer.rembg_menu_uninstall") in texts
                  and i18n.tr("viewer.rembg_menu_install") not in texts,
                  str(texts))
            check("заголовок rembg: установлен",
                  any(a.text().startswith("🪄")
                      and i18n.tr("modules.installed") in a.text()
                      for a in acts))
            # удаление из меню: подтверждение + pip uninstall
            win.local.rembg_uninstall()
            ok = wait_until(lambda: not win.local.rembg_is_busy())
            check("удаление из меню завершилось", ok)
            check("подтверждение удаления показано",
                  "quest" in box_calls, str(box_calls))
            check("pip вызван на удаление",
                  bool(calls) and calls[-1][:2] == ["uninstall", "-y"],
                  str(calls))
            check("об удалении сообщило окно",
                  box_calls[-1:] == ["info"], str(box_calls))
        finally:
            rembg_manager.is_installed = real_installed
    finally:
        rembg_manager._run_pip = real_pip
        QMessageBox.information = real_info
        QMessageBox.warning = real_warn
        QMessageBox.question = real_quest

    # ---------- занятый модуль: пункты установки запрещены ----------
    win.local._rembg_busy = True
    acts = actions_of(win._modules_menu)
    act_inst = next((a for a in acts
                     if a.text() == i18n.tr("viewer.rembg_menu_install")), None)
    check("пока busy — пункт установки запрещён",
          act_inst is not None and not act_inst.isEnabled())
    win.local._rembg_busy = False

    # ---------- перетрансляция ----------
    i18n.set_lang("en", persist=False)
    app.processEvents()
    check("заголовок меню переведён (en)",
          win._modules_menu.title() == i18n.tr("menu.modules"),
          win._modules_menu.title())
    i18n.set_lang("ru", persist=False)
    app.processEvents()
    check("заголовок меню переведён обратно (ru)",
          win._modules_menu.title() == i18n.tr("menu.modules"),
          win._modules_menu.title())

    # ---------- уборка ----------
    if win._server_mgr is not None:
        win._server_mgr.stop()
    st.setValue("server/autostart", False)

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} -> {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt в песочнице
