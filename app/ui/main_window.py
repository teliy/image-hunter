"""Главное окно Image Hunter: три вкладки — просмотр, поиск, загрузки."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, QThreadPool, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QStatusBar,
    QTabWidget,
    QToolButton,
)

from app import __version__
from app.core import updates, webp_saver
from app.core.downloader import Downloader
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

        self.tabs.addTab(self.local, "📁 Мои картинки")
        self.tabs.addTab(self.web, "🌐 Поиск картинок")
        self.tabs.addTab(self.downloads, "⬇️ Загрузки")
        self.setCentralWidget(self.tabs)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Готово: откройте папку на вкладке «Мои картинки» или найдите картинки во вкладке «Поиск».")

        # обновление прямо из интерфейса: кнопка в статус-баре + меню «Справка»
        btn_upd = QToolButton()
        btn_upd.setText("🔄 Обновить")
        btn_upd.setToolTip("Проверить обновления и обновиться прямо из программы (Ctrl+U)")
        btn_upd.setAutoRaise(True)
        btn_upd.clicked.connect(self.check_updates)
        self._status.addPermanentWidget(btn_upd)

        help_menu = self.menuBar().addMenu("&Справка")
        act_upd = help_menu.addAction("Проверить обновления…", self.check_updates)
        act_upd.setShortcut(QKeySequence("Ctrl+U"))
        help_menu.addAction("О программе", self._about)

        # найденные на странице выдачи ссылки → сразу в загрузки
        self.web.images_found.connect(self._on_images_found)
        self.web.save_webp_requested.connect(self._on_save_webp)
        self._downloader.batch_finished.connect(self._on_batch_finished)

    # ---------- обновление ----------

    def check_updates(self) -> None:
        self._status.showMessage("Проверяю обновления…")
        self._upd_signals = updates.UpdatesSignals()
        self._upd_signals.done.connect(self._on_version_checked)
        QThreadPool.globalInstance().start(updates.VersionCheckTask(self._upd_signals))

    def _on_version_checked(self, remote: str) -> None:
        if not remote:
            self._status.clearMessage()
            QMessageBox.warning(self, "Обновление",
                                "Не удалось проверить обновления.\nПроверьте подключение к интернету.")
            return
        if not updates.is_newer(remote, __version__):
            self._status.clearMessage()
            QMessageBox.information(self, "Обновление", f"У вас последняя версия — {__version__}.")
            return
        ans = QMessageBox.question(
            self, "Обновление",
            f"Доступна новая версия: {remote} (у вас {__version__}).\n\n"
            "Обновить сейчас? Приложение закроется, в отдельном окне запустится установщик,\n"
            "после завершения Image Hunter откроется сам.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        if updates.run_update_and_restart():
            self._status.showMessage("Обновление запущено — приложение закрывается…")
            QTimer.singleShot(400, QApplication.quit)
        else:
            self._status.clearMessage()
            QMessageBox.warning(
                self, "Обновление",
                "Рядом с программой не найден установщик (папка installer).\n"
                "Обновитесь командой: ImageHunter.bat update")

    # ---------- сохранение отмеченных как WebP ----------

    def _on_save_webp(self, urls: list, referer: str) -> None:
        """Отмеченные плитки → WebP в папку, открытую в «Моих картинках»."""
        if getattr(self, "_webp_saver", None) is not None and self._webp_saver.is_busy():
            self._status.showMessage("Дождитесь завершения текущего сохранения WebP.", 5000)
            return
        folder = self.local.current_folder()
        if not (folder and os.path.isdir(folder)):
            ans = QMessageBox.question(
                self, "Сохранить как WebP",
                "Во вкладке «Мои картинки» не открыта папка.\n\n"
                "Выбрать папку для сохранения WebP?")
            if ans != QMessageBox.StandardButton.Yes:
                return
            folder = QFileDialog.getExistingDirectory(self, "Папка для сохранения WebP")
            if not folder:
                return
            self.local.load_folder(folder, sync_tree=True)   # откроем её же в просмотре

        base_default = webp_saver.sanitize_base_name(self.web.query.text()) or "image"
        base, ok = QInputDialog.getText(
            self, "Сохранить как WebP",
            f"Имя файлов в папке «{os.path.basename(folder) or folder}»:\n"
            "первый файл — название.webp, дальше название-1.webp, название-2.webp…",
            text=base_default)
        if not ok:
            return
        base = webp_saver.sanitize_base_name(base) or "image"

        names = webp_saver.assign_webp_names(folder, base, len(urls))
        self._webp_folder = folder
        self._webp_total = len(names)
        self._webp_saved = 0
        self._webp_saver = webp_saver.WebpSaver(self)
        self._webp_saver.file_done.connect(self._on_webp_file_done)
        self._webp_saver.finished.connect(self._on_webp_finished)
        self._webp_saver.start(list(zip(urls, names)), referer or None, folder)
        self._status.showMessage(f"Сохраняю как WebP: 0 из {self._webp_total}…")

    def _on_webp_file_done(self, _index: int, ok: bool, info: str) -> None:
        if ok:
            self._webp_saved += 1
        else:
            self._status.showMessage(f"WebP: ошибка — {info}", 8000)
            return
        self._status.showMessage(
            f"Сохраняю как WebP: {self._webp_saved} из {self._webp_total}…")

    def _on_webp_finished(self, ok: int, fail: int, folder: str) -> None:
        tail = f", ошибок: {fail}" if fail else ""
        self._status.showMessage(f"WebP готово: {ok} сохранено{tail} → {folder}", 15000)
        if fail:
            QMessageBox.warning(
                self, "Сохранить как WebP",
                f"Сохранено: {ok}, ошибок: {fail}.\nПодробности — в статусной строке.")
        if self.local.current_folder() == folder:
            self.local.refresh()   # новые файлы сразу видны в «Моих картинках»

    def _about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            f"<b>Image Hunter {__version__}</b><br>"
            "Просмотр локальных изображений, поиск картинок в интернете и массовое скачивание.")

    # ---------- слоты ----------

    def _on_images_found(self, urls: list, referer: str) -> None:
        added = self.downloads.add_urls(urls, referer=referer or None)
        self.tabs.setCurrentWidget(self.downloads)
        if added:
            self._status.showMessage(f"Собрано ссылок: {added} — скачивание начато.", 8000)
        else:
            self._status.showMessage("Новых ссылок нет — они уже скачивались в этой сессии.", 8000)

    def _on_batch_finished(self, ok: int, fail: int) -> None:
        self._status.showMessage(f"Загрузка завершена: {ok} скачано, {fail} ошибок.", 10000)
