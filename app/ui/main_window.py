"""Главное окно Image Hunter: три вкладки — просмотр, поиск, загрузки."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow, QStatusBar, QTabWidget

from app.core.downloader import Downloader
from app.ui.downloads import DownloadsView
from app.ui.local_viewer import LocalViewer
from app.ui.web_search import WebSearch


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Hunter")
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

        # найденные на странице выдачи ссылки → сразу в загрузки
        self.web.images_found.connect(self._on_images_found)
        self._downloader.batch_finished.connect(self._on_batch_finished)

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
