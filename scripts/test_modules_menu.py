"""Оффлайн-тест меню «Модули» (v0.8.2; водяные знаки — v0.8.11).

Меню стоит в строке меню слева от «Справки» и собирается заново при
каждом открывании. Проверяется:

1. порядок меню: «Модули» → «Справка»;
2. раздел rembg: заголовок-состояние, установка/удаление по факту,
   строка версий установленного модуля (v0.8.17), подменю модели с
   галочкой; выбор модели сохраняется;
3. раздел водяных знаков (Florence-2 + LaMa): заголовок-состояние,
   установка/удаление, ОБНОВЛЕНИЕ установленного модуля (v0.8.15),
   строки версий конвейера и моделей — ревизия Florence-2, размер
   big-lama, честные «не скачана»/«версия неизвестна» (v0.8.17),
   подменю детектора; выбор детектора сохраняется;
4. раздел веб-сервера: заголовок-состояние, запуск/остановка,
   автостарт (галочка пишет настройку и журнал), панель;
5. «Перезагрузить Image Hunter» внизу меню (v0.8.17): клик запускает
   новый экземпляр и закрывает окно, отказ — честное предупреждение,
   пока busy — пункт запрещён;
6. ленивость: открытие меню не импортирует app.server;
7. пункты установки/удаления/модели ушли из контекстного меню ленты
   (вместе с пунктами обновления v0.8.15);
8. перетрансляция заголовка при смене языка.

Запуск: QT_QPA_PLATFORM=offscreen python scripts/test_modules_menu.py
"""

import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRunnable, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import __version__  # noqa: E402
from app.core import i18n, updates  # noqa: E402
from app.ui import rembg_manager, watermark_manager  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

FAILURES: list[str] = []

# префиксы недоступных строк-справок (до подстановки значений):
# «Версии: » и «Модели: » — по ним строки ищутся в любом языке;
# заполняются в main() ПОСЛЕ set_lang — при импорте язык ещё
# не выбран и берётся сохранённый в настройках (не обязан быть ru)
VERSIONS_PREFIX = ""
MODELS_PREFIX = ""


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
    global VERSIONS_PREFIX, MODELS_PREFIX
    app = QApplication.instance() or QApplication(sys.argv)
    i18n.set_lang("ru", persist=False)
    VERSIONS_PREFIX = i18n.tr("modules.versions", list="").split("{")[0]
    MODELS_PREFIX = i18n.tr("modules.models", list="").split("{")[0]

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

    check("версия 0.8.22", __version__ == "0.8.22", __version__)

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
    check("строк версий/моделей нет, пока модули не установлены",
          not any(a.text().startswith(VERSIONS_PREFIX) for a in acts)
          and not any(a.text().startswith(MODELS_PREFIX) for a in acts),
          str(texts))
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

    # ---------- раздел водяных знаков (в песочнице модуль не установлен) ----------
    acts = actions_of(win._modules_menu)
    texts = [a.text() for a in acts]
    head_w = next((a for a in acts if a.text().startswith("🧽")), None)
    check("заголовок водяных знаков: не установлен",
          head_w is not None and not head_w.isEnabled()
          and i18n.tr("modules.not_installed") in head_w.text(),
          head_w.text() if head_w else "?")
    check("пункт установки водяных знаков на месте",
          i18n.tr("viewer.wm_menu_install") in texts, str(texts))
    check("пункта удаления водяных знаков нет (модуль не установлен)",
          i18n.tr("viewer.wm_menu_uninstall") not in texts)
    m_det = next((a.menu() for a in acts
                  if a.menu() and a.text() == i18n.tr("viewer.wm_model_menu")),
                 None)
    check("подменю детектора Florence-2 есть", m_det is not None)
    dets = m_det.actions() if m_det else []
    check("в подменю два детектора",
          len(dets) == len(watermark_manager.FLORENCE_MODELS),
          str([a.text() for a in dets]))
    check("галочка на детекторе по умолчанию",
          any(a.isChecked() for a in dets), "")
    # выбор детектора из меню: сохраняется в настройках
    dets[1].trigger()
    app.processEvents()
    st.sync()
    check("выбор детектора из меню сохранён",
          win.local.wm_current_model() == watermark_manager.FLORENCE_MODELS[1][0]
          and st.value(watermark_manager.MODEL_KEY, "", type=str)
          == watermark_manager.FLORENCE_MODELS[1][0],
          win.local.wm_current_model())
    st.setValue(watermark_manager.MODEL_KEY, "")
    win.local.wm_set_model(watermark_manager.DEFAULT_MODEL)

    # «установленный» модуль: пункт удаления + заголовок
    real_wm_installed = watermark_manager.is_installed
    watermark_manager.is_installed = lambda: True
    try:
        acts = actions_of(win._modules_menu)
        texts = [a.text() for a in acts]
        check("установленный wm: пункт удаления",
              i18n.tr("viewer.wm_menu_uninstall") in texts
              and i18n.tr("viewer.wm_menu_install") not in texts, str(texts))
        check("установленный wm: пункт обновления",
              i18n.tr("viewer.wm_menu_update") in texts, str(texts))
        check("заголовок wm: установлен",
              any(a.text().startswith("🧽")
                  and i18n.tr("modules.installed") in a.text() for a in acts))
        # клик по пункту обновления запускает задачу с выбранным детектором
        real_upd_task_m = watermark_manager.UpdateTask
        upd_started_m: list[str] = []

        class StubMenuUpd(QRunnable):
            def __init__(self, signals, model):
                super().__init__()
                self.signals, self.model = signals, model
                upd_started_m.append(model)

            def run(self):
                # контракт задачи: what всегда непуст (тут — «актуально»)
                self.signals.update_done.emit(
                    True, i18n.tr("viewer.wm_update_nothing", pkgs="iopaint"), "")

        watermark_manager.UpdateTask = StubMenuUpd
        real_info_m = QMessageBox.information
        QMessageBox.information = lambda *a, **k: None
        try:
            act_upd = next((a for a in actions_of(win._modules_menu)
                            if a.text() == i18n.tr("viewer.wm_menu_update")),
                           None)
            check("пункт обновления wm на месте и активен",
                  act_upd is not None and act_upd.isEnabled())
            if act_upd is not None:
                act_upd.trigger()
                app.processEvents()
                check("пункт обновления wm запускает задачу с детектором",
                      upd_started_m == [win.local.wm_current_model()],
                      str(upd_started_m))
                wait_until(lambda: not win.local.wm_is_busy(), timeout_s=10)
        finally:
            watermark_manager.UpdateTask = real_upd_task_m
            QMessageBox.information = real_info_m

        # строки версий/моделей установленного конвейера (v0.8.17)
        real_wv = watermark_manager.installed_version
        real_fr = watermark_manager.florence_revision
        real_ls = watermark_manager.lama_size
        watermark_manager.installed_version = lambda n: {
            "iopaint": "1.6.0", "transformers": "4.48.3",
            "timm": "1.0.15"}.get(n, "")
        watermark_manager.florence_revision = lambda repo: "0123456789abcdef" * 5
        watermark_manager.lama_size = lambda: 196 * (1 << 20)
        try:
            acts = actions_of(win._modules_menu)
            head_w = next((a for a in acts if a.text().startswith("🧽")), None)
            vlines = [a for a in acts if a.text().startswith(VERSIONS_PREFIX)]
            check("установленный wm: строка версий всего конвейера",
                  len(vlines) >= 1 and not vlines[0].isEnabled()
                  and "iopaint 1.6.0" in vlines[0].text()
                  and "transformers 4.48.3" in vlines[0].text()
                  and "timm 1.0.15" in vlines[0].text(),
                  vlines[0].text() if vlines else "?")
            check("строка версий wm стоит прямо под заголовком",
                  head_w is not None and vlines
                  and acts.index(vlines[0]) == acts.index(head_w) + 1)
            mline = next((a for a in acts
                          if a.text().startswith(MODELS_PREFIX)), None)
            check("установленный wm: строка моделей — ревизия и размер",
                  mline is not None and not mline.isEnabled()
                  and "Florence-2-base rev 0123456" in mline.text()
                  and i18n.tr("modules.size_mb", mb=196) in mline.text(),
                  mline.text() if mline else "?")
            check("строка моделей идёт сразу за строкой версий",
                  mline is not None and vlines
                  and acts.index(mline) == acts.index(vlines[0]) + 1)
            # версии пакетов прочитать не удалось — честная справка
            watermark_manager.installed_version = lambda n: ""
            acts = actions_of(win._modules_menu)
            vlines = [a for a in acts if a.text().startswith(VERSIONS_PREFIX)]
            check("wm: неизвестная версия пакета помечена честно",
                  vlines and all(
                      i18n.tr("modules.version_unknown") in a.text()
                      for a in vlines),
                  vlines[0].text() if vlines else "?")
            # модели ещё не качались — так и написано
            watermark_manager.florence_revision = lambda repo: ""
            watermark_manager.lama_size = lambda: 0
            acts = actions_of(win._modules_menu)
            mline = next((a for a in acts
                          if a.text().startswith(MODELS_PREFIX)), None)
            check("wm: нескачанные модели помечены честно",
                  mline is not None
                  and i18n.tr("modules.model_not_downloaded") in mline.text()
                  and mline.text().count(i18n.tr("modules.model_not_downloaded")) == 2,
                  mline.text() if mline else "?")
        finally:
            watermark_manager.installed_version = real_wv
            watermark_manager.florence_revision = real_fr
            watermark_manager.lama_size = real_ls
    finally:
        watermark_manager.is_installed = real_wm_installed

    # меню пересобирается при каждом aboutToShow — прежние QAction удалены
    acts = actions_of(win._modules_menu)
    texts = [a.text() for a in acts]

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
    check("в контекст-меню ленты есть «Убрать водяные знаки»",
          i18n.tr("viewer.wm") in names, str(names))
    check("в контекст-меню нет подменю модели",
          not any(a.menu() for a in menu.actions()), str(names))
    check("в контекст-меню нет установки/удаления/обновления модуля",
          i18n.tr("viewer.rembg_menu_install") not in names
          and i18n.tr("viewer.rembg_menu_uninstall") not in names
          and i18n.tr("viewer.rembg_menu_update") not in names
          and i18n.tr("viewer.wm_menu_install") not in names
          and i18n.tr("viewer.wm_menu_uninstall") not in names
          and i18n.tr("viewer.wm_menu_update") not in names, str(names))
    check("словарь действий без inst/uninst",
          set(lv_acts) == {"open", "copy", "rename", "bg", "wm", "del"},
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
            check("установленный модуль: пункт обновления",
                  i18n.tr("viewer.rembg_menu_update") in texts, str(texts))
            check("заголовок rembg: установлен",
                  any(a.text().startswith("🪄")
                      and i18n.tr("modules.installed") in a.text()
                      for a in acts))
            # строка версий установленного модуля (v0.8.17): пакет rembg
            real_rv = rembg_manager.installed_version
            rembg_manager.installed_version = lambda: "2.0.61"
            try:
                acts = actions_of(win._modules_menu)
                head_r = next((a for a in acts if a.text().startswith("🪄")), None)
                vline = next((a for a in acts
                              if a.text().startswith(VERSIONS_PREFIX)), None)
                check("установленный rembg: строка версий есть и недоступна",
                      vline is not None and not vline.isEnabled()
                      and "rembg 2.0.61" in vline.text(),
                      vline.text() if vline else "?")
                check("строка версий rembg стоит прямо под заголовком",
                      head_r is not None and vline is not None
                      and acts.index(vline) == acts.index(head_r) + 1)
                # неизвестная версия — честная справка вместо пустоты
                rembg_manager.installed_version = lambda: ""
                acts = actions_of(win._modules_menu)
                vline = next((a for a in acts
                              if a.text().startswith(VERSIONS_PREFIX)), None)
                check("rembg: неизвестная версия помечена честно",
                      vline is not None
                      and i18n.tr("modules.version_unknown") in vline.text(),
                      vline.text() if vline else "?")
            finally:
                rembg_manager.installed_version = real_rv
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

    # ---------- занятый модуль: пункты установки/обновления запрещены ----------
    win.local._rembg_busy = True
    acts = actions_of(win._modules_menu)
    act_inst = next((a for a in acts
                     if a.text() == i18n.tr("viewer.rembg_menu_install")), None)
    check("пока busy — пункт установки запрещён",
          act_inst is not None and not act_inst.isEnabled())
    win.local._rembg_busy = False
    win.local._rembg_busy = True
    real_inst_busy_r = rembg_manager.is_installed
    rembg_manager.is_installed = lambda: True   # пункт обновления есть лишь у установленного
    acts = actions_of(win._modules_menu)
    act_upd_r = next((a for a in acts
                      if a.text() == i18n.tr("viewer.rembg_menu_update")), None)
    check("пока busy rembg — пункт обновления запрещён",
          act_upd_r is not None and not act_upd_r.isEnabled())
    rembg_manager.is_installed = real_inst_busy_r
    win.local._rembg_busy = False
    win.local._wm_busy = True
    acts = actions_of(win._modules_menu)
    act_wm = next((a for a in acts
                   if a.text() == i18n.tr("viewer.wm_menu_install")), None)
    check("пока busy wm — пункт установки водяных знаков запрещён",
          act_wm is not None and not act_wm.isEnabled())
    real_inst_busy_w = watermark_manager.is_installed
    watermark_manager.is_installed = lambda: True
    acts = actions_of(win._modules_menu)
    act_upd_w = next((a for a in acts
                      if a.text() == i18n.tr("viewer.wm_menu_update")), None)
    check("пока busy wm — пункт обновления запрещён",
          act_upd_w is not None and not act_upd_w.isEnabled())
    watermark_manager.is_installed = real_inst_busy_w
    win.local._wm_busy = False

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

    # ---------- «Перезагрузить Image Hunter» (v0.8.17) ----------
    win.show()
    app.processEvents()
    acts = actions_of(win._modules_menu)
    act_rst = next((a for a in acts if a.text() == i18n.tr("modules.restart")),
                   None)
    check("пункт «Перезагрузить Image Hunter» есть и активен",
          act_rst is not None and act_rst.isEnabled(),
          act_rst.text() if act_rst else "?")
    check("пункт перезагрузки — после раздела сервера, в конце меню",
          act_rst is not None
          and acts.index(act_rst) == len(acts) - 1
          and any(a.text().startswith("🌐") for a in acts[:acts.index(act_rst)]))
    restart_calls: list[bool] = []
    real_start_restart = updates.start_restart
    updates.start_restart = lambda: (restart_calls.append(True), True)[1]
    warn_calls: list[str] = []
    real_warn_r = QMessageBox.warning
    QMessageBox.warning = lambda *a, **k: warn_calls.append("warn")
    try:
        act_rst.trigger()
        app.processEvents()
        check("клик по пункту запускает новый экземпляр",
              restart_calls == [True], str(restart_calls))
        check("окно закрылось — программа перезагружается",
              not win.isVisible())
        # отказ запуска: честное предупреждение вместо молчания
        updates.start_restart = lambda: (restart_calls.append(False), False)[1]
        win.restart_app()
        app.processEvents()
        check("при отказе запуска показано предупреждение",
              warn_calls == ["warn"], str(warn_calls))
    finally:
        updates.start_restart = real_start_restart
        QMessageBox.warning = real_warn_r
    # пока pip занят — перезагрузка оборвала бы установку: пункт запрещён
    win.local._rembg_busy = True
    act_rst = next((a for a in actions_of(win._modules_menu)
                    if a.text() == i18n.tr("modules.restart")), None)
    check("пока busy rembg — пункт перезагрузки запрещён",
          act_rst is not None and not act_rst.isEnabled())
    win.local._rembg_busy = False
    win.local._wm_busy = True
    act_rst = next((a for a in actions_of(win._modules_menu)
                    if a.text() == i18n.tr("modules.restart")), None)
    check("пока busy wm — пункт перезагрузки запрещён",
          act_rst is not None and not act_rst.isEnabled())
    win.local._wm_busy = False
    act_rst = next((a for a in actions_of(win._modules_menu)
                    if a.text() == i18n.tr("modules.restart")), None)
    check("после busy пункт перезагрузки снова активен",
          act_rst is not None and act_rst.isEnabled())

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
