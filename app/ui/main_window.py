"""Главное окно Image Hunter: три вкладки — просмотр, поиск, загрузки."""

from __future__ import annotations

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
from app.core import i18n, image_saver, updates
from app.core.downloader import Downloader
from app.core.i18n import lang_name, tr
from app.ui.downloads import DownloadsView
from app.ui.local_viewer import LocalViewer
from app.ui.web_search import WebSearch


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Image Hunter {__version__}")
        self.resize(1280, 820)
        self.setMinimumSize(QSize(960, 600))

        self._downloader = Downloader(self)

        self.tabs = QTabWidget()
        self.local = LocalViewer()
        self.web = WebSearch()
        self.downloads = DownloadsView(self._downloader)

        self.tabs.addTab(self.local, tr("tab.pictures"))
        self.tabs.addTab(self.web, tr("tab.search"))
        self.tabs.addTab(self.downloads, tr("tab.downloads"))
        self.setCentralWidget(self.tabs)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(tr("main.ready"))

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

        # найденные на странице выдачи ссылки → сразу в загрузки;
        # отмеченные плитки → сохранение в выбранном формате
        self.web.images_found.connect(self._on_images_found)
        self.web.save_requested.connect(self._on_save_images)
        self._downloader.batch_finished.connect(self._on_batch_finished)

        i18n.signals.changed.connect(self._retranslate)

    # ---------- язык интерфейса ----------

    def _on_lang_changed(self, index: int) -> None:
        code = i18n.LANG_ITEMS[index][0]
        i18n.set_lang(code)   # сигнал changed перетранслирует все окна
        self._status.showMessage(tr("main.lang_changed", name=lang_name(code)), 5000)

    def _retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка)."""
        self.setWindowTitle(f"Image Hunter {__version__}")
        self.tabs.setTabText(0, tr("tab.pictures"))
        self.tabs.setTabText(1, tr("tab.search"))
        self.tabs.setTabText(2, tr("tab.downloads"))
        self.btn_upd.setText("🔄 " + tr("main.update"))
        self.btn_upd.setToolTip(tr("main.update_tip"))
        self.lang_box.setToolTip(tr("main.lang_tip"))
        self._help_menu.setTitle(tr("menu.help"))
        self.act_upd.setText(tr("main.check_updates"))
        self.act_about.setText(tr("main.about_action"))

    # ---------- обновление ----------

    def check_updates(self) -> None:
        self._status.showMessage(tr("main.upd_checking"))
        self._upd_signals = updates.UpdatesSignals()
        self._upd_signals.done.connect(self._on_version_checked)
        QThreadPool.globalInstance().start(updates.VersionCheckTask(self._upd_signals))

    def _on_version_checked(self, remote: str) -> None:
        if not remote:
            self._status.clearMessage()
            QMessageBox.warning(self, tr("main.upd_title"), tr("main.upd_check_fail"))
            return
        if not updates.is_newer(remote, __version__):
            self._status.clearMessage()
            QMessageBox.information(self, tr("main.upd_title"),
                                    tr("main.upd_latest", version=__version__))
            return
        ans = QMessageBox.question(
            self, tr("main.upd_title"),
            tr("main.upd_available", remote=remote, current=__version__))
        if ans != QMessageBox.StandardButton.Yes:
            return
        if updates.run_update_and_restart():
            self._status.showMessage(tr("main.upd_running"))
            QTimer.singleShot(400, QApplication.quit)
        else:
            self._status.clearMessage()
            QMessageBox.warning(self, tr("main.upd_title"), tr("main.upd_no_installer"))

    # ---------- сохранение отмеченных в выбранном формате ----------

    def _on_save_images(self, urls: list, referer: str) -> None:
        """Отмеченные плитки → выбранный формат → папка из «Моих картинок»."""
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
            self.local.load_folder(folder, sync_tree=True)   # откроем её же в просмотре

        ext = image_saver.SAVE_FORMATS[fmt][1]
        base_default = image_saver.sanitize_base_name(self.web.query.text()) or "image"
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
        self._img_folder = folder
        self._img_total = len(names)
        self._img_saved = 0
        self._img_saver = image_saver.ImageSaver(self)
        self._img_saver.file_done.connect(self._on_save_file_done)
        self._img_saver.finished.connect(self._on_save_finished)
        self._img_saver.start(list(zip(urls, names)), referer or None, folder, base, fmt)
        self._status.showMessage(
            tr("main.saving", fmt=fmt, done=0, total=self._img_total))

    def _on_save_file_done(self, _index: int, ok: bool, info: str) -> None:
        if ok:
            self._img_saved += 1
        else:
            self._status.showMessage(tr("main.save_err", info=info), 8000)
            return
        self._status.showMessage(
            tr("main.saving", fmt=self.web.current_format(),
               done=self._img_saved, total=self._img_total))

    def _on_save_finished(self, ok: int, fail: int, folder: str) -> None:
        tail = tr("main.save_done_tail", fail=fail) if fail else ""
        self._status.showMessage(
            tr("main.save_done", ok=ok, tail=tail, folder=folder), 15000)
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

    def _on_images_found(self, urls: list, referer: str) -> None:
        added = self.downloads.add_urls(urls, referer=referer or None)
        self.tabs.setCurrentWidget(self.downloads)
        if added:
            self._status.showMessage(tr("main.collected", n=added), 8000)
        else:
            self._status.showMessage(tr("dl.no_new"), 8000)

    def _on_batch_finished(self, ok: int, fail: int) -> None:
        self._status.showMessage(tr("dl.summary_ready", ok=ok, fail=fail), 10000)
