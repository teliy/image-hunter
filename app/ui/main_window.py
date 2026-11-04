"""Главное окно Image Hunter: вкладки — просмотр, поиск, загрузки и журнал.

Вкладки можно перетаскивать мышью и переставлять (setMovable), вкладка
«Журнал» добавлена самой правой: в ней видна хроника всей работы.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QSize, QThreadPool, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolButton,
)

from app import __version__
from app.core import applog, i18n, image_saver, updates
from app.core.downloader import Downloader
from app.core.i18n import lang_name, tr
from app.ui.app_icon import icon as app_icon
from app.ui.downloads import DownloadsView
from app.ui.local_viewer import LocalViewer
from app.ui.log_view import LogView
from app.ui.search_tabs import SearchTabs


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Image Hunter {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self.setMinimumSize(QSize(960, 600))

        self._downloader = Downloader(self)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)   # вкладки перетаскиваются мышью и переставляются
        self.local = LocalViewer()
        # «Поиск картинок» — мультивкладки как в браузере: дублировать,
        # закрывать, «＋»; заголовок/цвет вложенной вкладки = поисковик
        self.web = SearchTabs()
        self.downloads = DownloadsView(self._downloader)
        self.log_view = LogView()

        self.tabs.addTab(self.local, tr("tab.pictures"))
        self.tabs.addTab(self.web, tr("tab.search"))
        self.tabs.addTab(self.downloads, tr("tab.downloads"))
        self.tabs.addTab(self.log_view, tr("tab.log"))   # журнал — самой правой
        self.setCentralWidget(self.tabs)

        # порядок вкладок мог измениться — заголовки ищем по виджету, не по номеру
        self._tab_keys = ((self.local, "tab.pictures"), (self.web, "tab.search"),
                          (self.downloads, "tab.downloads"), (self.log_view, "tab.log"))

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(tr("main.ready"))

        # текущее задание — не только в журнале, но и внизу (v0.7.13): каждая
        # строка журнала дублируется в левую часть статус-бара, так что что бы
        # ни делала программа (поиск, скачивание, установка модуля, синхро-
        # низация дерева) — видно без открывания вкладки «Журнал»
        applog.bridge.plain.connect(self._on_log_record)

        # статус вкладки «Мои картинки» (поиск по имени, копирование, удаление)
        # теперь живёт здесь, внизу: слева от языка и кнопки обновления (v0.7.7)
        self._status.addPermanentWidget(self.local.status)

        # веб-сервер (v0.8.0): кнопка «🌐» открывает окно удалённого доступа.
        # Модуль app/server ленивый: до первого клика не импортируется и не
        # занимает ни портов, ни потоков — удаление папки app/server и этой
        # кнопки полностью убирает модуль из программы
        self._server_mgr = None          # app.server.manager.ServerManager
        self._server_dlg = None          # app.server.dialog.ServerDialog
        self.btn_server = QToolButton()
        self.btn_server.setText("🌐")
        self.btn_server.setToolTip(tr("server.tip"))
        self.btn_server.setAutoRaise(True)
        self.btn_server.clicked.connect(self.show_server_dialog)
        self._status.addPermanentWidget(self.btn_server)

        # выбор языка интерфейса: Русский / English / 中文 (запоминается)
        self.lang_box = QComboBox()
        for _code, name in i18n.LANG_ITEMS:
            self.lang_box.addItem(name)
        codes = [code for code, _ in i18n.LANG_ITEMS]
        self.lang_box.setCurrentIndex(codes.index(i18n.current_lang()))
        self.lang_box.setToolTip(tr("main.lang_tip"))
        self.lang_box.currentIndexChanged.connect(self._on_lang_changed)
        self._status.addPermanentWidget(self.lang_box)

        # обновление прямо из интерфейса: кнопка в статус-баре + меню «Справка»
        self.btn_upd = QToolButton()
        self.btn_upd.setText("🔄 " + tr("main.update"))
        self.btn_upd.setToolTip(tr("main.update_tip"))
        self.btn_upd.setAutoRaise(True)
        self.btn_upd.clicked.connect(self.check_updates)
        self._status.addPermanentWidget(self.btn_upd)

        self._help_menu = self.menuBar().addMenu(tr("menu.help"))
        self.act_upd = self._help_menu.addAction(tr("main.check_updates"), self.check_updates)
        self.act_upd.setShortcut(QKeySequence("Ctrl+U"))
        self.act_about = self._help_menu.addAction(tr("main.about_action"), self._about)

        # автостарт веб-сервера (v0.8.0): настройки мог включить заранее;
        # поднимаем чуть позже показа окна — старт программы не ждёт сеть
        from PySide6.QtCore import QSettings
        if QSettings("ImageHunter", "ImageHunter").value(
                "server/autostart", False, type=bool):
            QTimer.singleShot(1200, self._server_autostart)

        # найденные на странице выдачи ссылки → сразу в загрузки;
        # отмеченные плитки → сохранение в выбранном формате
        self.web.images_found.connect(self._on_images_found)
        self.web.save_requested.connect(self._on_save_images)
        self._downloader.batch_finished.connect(self._on_batch_finished)

        i18n.signals.changed.connect(self._retranslate)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """При закрытии запомнить последнюю папку и запрос поиска —
        оба восстановятся при следующем запуске. Веб-сервер, если работал,
        останавливается: после выхода программы доступ с телефона закрыт."""
        self.local.save_state()
        if self._server_mgr is not None:
            self._server_mgr.stop()
        super().closeEvent(event)

    # ---------- веб-сервер (удалённый доступ, v0.8.0) ----------

    def show_server_dialog(self) -> None:
        """Окно веб-сервера — лениво: ни импорта, ни объектов до первого клика."""
        if self._server_mgr is None:
            from app.server.manager import ServerManager
            self._server_mgr = ServerManager()
            self._server_mgr.state_changed.connect(self._on_server_state)
        if self._server_dlg is None:
            from app.server.dialog import ServerDialog
            self._server_dlg = ServerDialog(self._server_mgr, self)
        self._server_dlg.show()
        self._server_dlg.raise_()
        self._server_dlg.activateWindow()

    def _server_autostart(self) -> None:
        if self._server_mgr is None:
            from app.server.manager import ServerManager
            self._server_mgr = ServerManager()
            self._server_mgr.state_changed.connect(self._on_server_state)
        self._server_mgr.start()

    def _on_server_state(self, running: bool) -> None:
        """Кнопка «🌐» подсвечена, пока сервер работает, — состояние видно
        из любой вкладки без открывания окна настроек."""
        self.btn_server.setText("🌐◀" if running else "🌐")
        self.btn_server.setStyleSheet(
            "color:#569cd6; font-weight:bold;" if running else "")

    # ---------- язык интерфейса ----------

    def _on_lang_changed(self, index: int) -> None:
        code = i18n.LANG_ITEMS[index][0]
        i18n.set_lang(code)   # сигнал changed перетранслирует все окна
        self._status.showMessage(tr("main.lang_changed", name=lang_name(code)), 5000)
        applog.event("main.lang_changed", name=lang_name(code))

    def _retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка).

        Заголовки вкладок ищутся по виджету (indexOf), а не по номеру:
        вкладки перетаскиваются мышью, и их порядок мог поменяться."""
        self.setWindowTitle(f"Image Hunter {__version__}")
        for widget, key in self._tab_keys:
            index = self.tabs.indexOf(widget)
            if index >= 0:
                self.tabs.setTabText(index, tr(key))
        self.log_view.retranslate()
        self.btn_upd.setText("🔄 " + tr("main.update"))
        self.btn_upd.setToolTip(tr("main.update_tip"))
        self.btn_server.setToolTip(tr("server.tip"))
        self.lang_box.setToolTip(tr("main.lang_tip"))
        self._help_menu.setTitle(tr("menu.help"))
        self.act_upd.setText(tr("main.check_updates"))
        self.act_about.setText(tr("main.about_action"))

    # ---------- обновление ----------

    def check_updates(self) -> None:
        # защита от повторного клика (v0.7.11): каждая проверка — сетевой
        # запрос и диалог по завершении; двойной клик плодил и то и другое
        if getattr(self, "_upd_checking", False):
            return
        self._upd_checking = True
        self._status.showMessage(tr("main.upd_checking"))
        applog.event("main.upd_checking")
        self._upd_signals = updates.UpdatesSignals()
        self._upd_signals.done.connect(self._on_version_checked)
        QThreadPool.globalInstance().start(updates.VersionCheckTask(self._upd_signals))

    def _on_version_checked(self, remote: str) -> None:
        self._upd_checking = False   # проверка закончилась — можно проверять снова
        if not remote:
            self._status.clearMessage()
            applog.warning(tr("main.upd_check_fail"))
            QMessageBox.warning(self, tr("main.upd_title"), tr("main.upd_check_fail"))
            return
        if not updates.is_newer(remote, __version__):
            self._status.clearMessage()
            applog.event("log.event.upd_latest", version=__version__)
            QMessageBox.information(self, tr("main.upd_title"),
                                    tr("main.upd_latest", version=__version__))
            return
        applog.event("log.event.upd_available", remote=remote)
        ans = QMessageBox.question(
            self, tr("main.upd_title"),
            tr("main.upd_available", remote=remote, current=__version__))
        if ans != QMessageBox.StandardButton.Yes:
            return
        if updates.run_update_and_restart():
            applog.event("log.event.upd_started")
            # без единого окна терминала: обновление идёт в скрытом сеансе,
            # пользователь должен знать, чего ждать, пока приложение закрыто
            QMessageBox.information(self, tr("main.upd_title"),
                                    tr("main.upd_running"))
            QTimer.singleShot(200, QApplication.quit)
        else:
            self._status.clearMessage()
            QMessageBox.warning(self, tr("main.upd_title"), tr("main.upd_no_installer"))

    # ---------- сохранение отмеченных в выбранном формате ----------

    def _on_save_images(self, urls: list, referer: str, engine: str = "") -> None:
        """Отмеченные плитки → выбранный формат → папка из «Моих картинок».

        ``engine`` — имя поисковика вкладки, из которой пришли картинки:
        попадает в журнал вместе с результатом сохранения (v0.7.8)."""
        self._img_engine = engine
        fmt = self.web.current_format()
        if getattr(self, "_img_saver", None) is not None and self._img_saver.is_busy():
            self._status.showMessage(tr("main.save_busy"), 5000)
            return
        folder = self.local.current_folder()
        if not (folder and os.path.isdir(folder)):
            ans = QMessageBox.question(
                self, tr("main.save_title", fmt=fmt), tr("main.save_no_folder"))
            if ans != QMessageBox.StandardButton.Yes:
                return
            folder = QFileDialog.getExistingDirectory(self, tr("main.save_pick_title"))
            if not folder:
                return
            self.local.load_folder(folder)      # откроем её же в просмотре
            self.local.show_in_tree(folder)     # подсветка без замираний (v0.7.11)

        ext = image_saver.SAVE_FORMATS[fmt][1]
        base_default = image_saver.sanitize_base_name(self.web.current_query()) or "image"
        base, ok = QInputDialog.getText(
            self, tr("main.save_title", fmt=fmt),
            tr("main.save_name_prompt",
               folder=os.path.basename(folder) or folder,
               base=tr("main.save_name_example"), ext=ext),
            text=base_default)
        if not ok:
            return
        base = image_saver.sanitize_base_name(base) or "image"

        names = image_saver.assign_image_names(folder, base, ext, len(urls))
        self._img_urls = list(urls)   # для журнала: какая ссылка не сохранилась
        self._img_folder = folder
        self._img_total = len(names)
        self._img_saved = 0
        self._img_saver = image_saver.ImageSaver(self)
        self._img_saver.file_done.connect(self._on_save_file_done)
        self._img_saver.finished.connect(self._on_save_finished)
        self._img_saver.start(list(zip(urls, names)), referer or None, folder, base, fmt)
        self._status.showMessage(
            tr("main.saving", fmt=fmt, done=0, total=self._img_total))

    def _on_save_file_done(self, index: int, ok: bool, info: str) -> None:
        if ok:
            self._img_saved += 1
        else:
            # причина ошибки — в журнал (в статус-баре она мелькает лишь 8 секунд)
            url = (self._img_urls[index] if 0 <= index < len(self._img_urls) else "?")
            applog.error(tr("log.event.save_file_err", url=url, err=info,
                            engine=getattr(self, "_img_engine", "")))
            self._status.showMessage(tr("main.save_err", info=info), 8000)
            return
        self._status.showMessage(
            tr("main.saving", fmt=self.web.current_format(),
               done=self._img_saved, total=self._img_total))

    def _on_save_finished(self, ok: int, fail: int, folder: str) -> None:
        tail = tr("main.save_done_tail", fail=fail) if fail else ""
        self._status.showMessage(
            tr("main.save_done", ok=ok, tail=tail, folder=folder), 15000)
        applog.event("log.event.save_done", ok=ok, fail=fail, folder=folder,
                     engine=getattr(self, "_img_engine", ""))
        if fail:
            QMessageBox.warning(
                self, tr("main.save_title", fmt=self.web.current_format()),
                tr("main.save_warn", ok=ok, fail=fail))
        if self.local.current_folder() == folder:
            self.local.refresh()   # новые файлы сразу видны в «Моих картинках»

    def _about(self) -> None:
        QMessageBox.about(self, tr("main.about_action"),
                          tr("main.about", version=__version__))

    # ---------- слоты ----------

    def _on_images_found(self, urls: list, referer: str, engine: str = "") -> None:
        added = self.downloads.add_urls(urls, referer=referer or None)
        self.tabs.setCurrentWidget(self.downloads)
        applog.event("log.event.collect", total=len(urls), added=added,
                     engine=engine)
        if added:
            self._status.showMessage(tr("main.collected", n=added), 8000)
        else:
            self._status.showMessage(tr("dl.no_new"), 8000)

    def _on_batch_finished(self, ok: int, fail: int) -> None:
        self._status.showMessage(tr("dl.summary_ready", ok=ok, fail=fail), 10000)
        applog.event("log.event.dl_done", ok=ok, fail=fail)

    # ---------- журнал → статусная строка ----------

    LOG_STATUS_MAX = 220

    def _on_log_record(self, level: int, msg: str) -> None:
        """Строка журнала — внизу, в статусной строке (v0.7.13).

        Журнал — полная хроника работы, но вкладку ещё надо открыть; мост
        дублирует каждую запись в статус-бар, поэтому текущее задание
        всегда видно без переключения вкладок. Показываем INFO и выше
        (DEBUG — технический шум), многострочные записи (трассировки
        ошибок) — только первой строкой, слишком длинные — обрезаем.
        Сообщение висит, пока его не сменит следующее событие: программа
        «рассказывает», чем занята, в темпе своей работы.
        """
        if level < logging.INFO:
            return
        line = ""
        for ln in (msg or "").splitlines():
            ln = ln.strip()
            if ln:
                line = ln          # первое непустое: у трассировок это заголовок
                break
        if not line:
            return
        if len(line) > self.LOG_STATUS_MAX:
            line = line[: self.LOG_STATUS_MAX - 1] + "…"
        self._status.showMessage(line)
