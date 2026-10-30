"""Вкладка «Загрузки»: очередь скачивания ссылок и таблица результатов."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import i18n
from app.core.downloader import Downloader, saved_download_dir, store_download_dir
from app.core.i18n import tr

# канонические статусы загрузчика → ключи перевода
_STATUS_KEYS = {
    "ok": "dl.status_done",
    "error": "dl.status_error",
    "cancel": "dl.status_cancel",
}


class DownloadsView(QWidget):
    """Приём ссылок (из вкладки поиска или вставленных вручную) и скачивание."""

    def __init__(self, downloader: Downloader, parent=None, download_dir: str | None = None):
        super().__init__(parent)
        self._downloader = downloader
        self._dir = download_dir or saved_download_dir()
        self._row_by_id: dict[int, int] = {}
        self._ok = 0
        self._fail = 0

        # --- папка сохранения ---
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 4)
        self.folder_label = QLabel(tr("dl.folder"))
        top.addWidget(self.folder_label)
        self.dir_label = QLabel(self._dir)
        self.dir_label.setStyleSheet("color: #444;")
        self.change_btn = QToolButton()
        self.change_btn.setText(tr("dl.change"))
        self.change_btn.clicked.connect(self.change_dir)
        self.open_btn = QToolButton()
        self.open_btn.setText(tr("dl.open"))
        self.open_btn.setToolTip(tr("dl.open_tip"))
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._dir))
        )
        top.addWidget(self.dir_label, 1)
        top.addWidget(self.change_btn)
        top.addWidget(self.open_btn)

        # --- вставка ссылок вручную ---
        mid = QHBoxLayout()
        mid.setContentsMargins(6, 4, 6, 4)
        self.paste_box = QPlainTextEdit()
        self.paste_box.setPlaceholderText(tr("dl.paste_ph"))
        self.paste_box.setFixedHeight(84)
        self.add_btn = QPushButton(tr("dl.download"))
        self.add_btn.clicked.connect(self._download_pasted)
        self.stop_btn = QPushButton(tr("dl.stop"))
        self.stop_btn.setToolTip(tr("dl.stop_tip"))
        self.stop_btn.clicked.connect(self._downloader.stop)
        mid.addWidget(self.paste_box, 1)
        mid.addWidget(self.add_btn)
        mid.addWidget(self.stop_btn)

        # --- таблица результатов ---
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("dl.h_link"), tr("dl.h_status"), tr("dl.h_file")])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 520)
        header.resizeSection(1, 90)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #666;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addLayout(mid)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.summary)

        self._downloader.status_changed.connect(self._on_status)
        self._downloader.batch_finished.connect(self._on_batch_finished)
        self._update_summary()
        i18n.signals.changed.connect(self._retranslate)

    # ---------- перетрансляция при смене языка ----------

    def _retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка)."""
        self.folder_label.setText(tr("dl.folder"))
        self.change_btn.setText(tr("dl.change"))
        self.open_btn.setText(tr("dl.open"))
        self.open_btn.setToolTip(tr("dl.open_tip"))
        self.paste_box.setPlaceholderText(tr("dl.paste_ph"))
        self.add_btn.setText(tr("dl.download"))
        self.stop_btn.setText(tr("dl.stop"))
        self.stop_btn.setToolTip(tr("dl.stop_tip"))
        self.table.setHorizontalHeaderLabels(
            [tr("dl.h_link"), tr("dl.h_status"), tr("dl.h_file")])
        self._update_summary()

    # ---------- публичное ----------

    def add_urls(self, urls, referer: str | None = None) -> int:
        """Добавить ссылки в очередь. Возвращает число новых ссылок."""
        items = self._downloader.add(urls)
        if not items:
            return 0
        for row_id, url in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            url_item = QTableWidgetItem(url)
            url_item.setData(Qt.UserRole, row_id)
            url_item.setToolTip(url)
            self.table.setItem(row, 0, url_item)
            self.table.setItem(row, 1, QTableWidgetItem(tr("dl.status_queue")))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self._row_by_id[row_id] = row
        self._downloader.start(items, referer, self._dir)
        self._update_summary()
        return len(items)

    # ---------- обработчики ----------

    def _download_pasted(self) -> None:
        urls = [line.strip() for line in self.paste_box.toPlainText().splitlines() if line.strip()]
        if not urls:
            QMessageBox.information(self, "Image Hunter", tr("dl.paste_first"))
            return
        added = self.add_urls(urls)
        if added == 0:
            QMessageBox.information(self, "Image Hunter", tr("dl.no_new"))
            return
        if added < len(urls):
            self.summary.setText(tr("dl.added", added=added, total=len(urls)))
        self.paste_box.clear()

    def _on_status(self, row_id: int, status: str, detail: str) -> None:
        row = self._row_by_id.get(row_id)
        if row is None:
            return
        status_item = self.table.item(row, 1)
        detail_item = self.table.item(row, 2)
        if status_item is None or detail_item is None:
            return
        status_item.setText(tr(_STATUS_KEYS.get(status, status)))
        detail_item.setText(detail)
        detail_item.setToolTip(detail)
        if status == "ok":
            self._ok += 1
            self._ok_color(status_item, "#1a7f37")
        elif status == "error":
            self._fail += 1
            self._ok_color(status_item, "#c62828")
        self._update_summary()

    def _on_batch_finished(self, ok: int, fail: int) -> None:
        self.summary.setText(tr("dl.batch_done", ok=ok, fail=fail, dir=self._dir))

    # ---------- служебное ----------

    @staticmethod
    def _ok_color(item: QTableWidgetItem, color: str) -> None:
        item.setForeground(Qt.green if color == "#1a7f37" else Qt.red)

    def _update_summary(self) -> None:
        total = self.table.rowCount()
        self.summary.setText(tr("dl.summary", n=total, ok=self._ok, fail=self._fail))

    def change_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("dl.pick_folder"), self._dir)
        if not directory:
            return
        self._dir = directory
        self.dir_label.setText(directory)
        store_download_dir(directory)
