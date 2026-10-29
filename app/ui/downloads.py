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

from app.core.downloader import Downloader, saved_download_dir, store_download_dir


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
        top.addWidget(QLabel("Папка:"))
        self.dir_label = QLabel(self._dir)
        self.dir_label.setStyleSheet("color: #444;")
        change = QToolButton()
        change.setText("Изменить…")
        change.clicked.connect(self.change_dir)
        open_btn = QToolButton()
        open_btn.setText("Открыть")
        open_btn.setToolTip("Открыть папку в Проводнике")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._dir))
        )
        top.addWidget(self.dir_label, 1)
        top.addWidget(change)
        top.addWidget(open_btn)

        # --- вставка ссылок вручную ---
        mid = QHBoxLayout()
        mid.setContentsMargins(6, 4, 6, 4)
        self.paste_box = QPlainTextEdit()
        self.paste_box.setPlaceholderText(
            "Вставьте прямые ссылки на картинки — по одной в строке…\n"
            "Ссылки с вкладки «Поиск картинок» попадают сюда автоматически."
        )
        self.paste_box.setFixedHeight(84)
        add = QPushButton("⬇ Скачать ссылки")
        add.clicked.connect(self._download_pasted)
        stop = QPushButton("■ Остановить")
        stop.setToolTip("Отменить всё, что ещё не начало скачиваться")
        stop.clicked.connect(self._downloader.stop)
        mid.addWidget(self.paste_box, 1)
        mid.addWidget(add)
        mid.addWidget(stop)

        # --- таблица результатов ---
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Ссылка", "Статус", "Файл / ошибка"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 520)
        header.resizeSection(1, 90)

        self.summary = QLabel("Готово: 0 скачано, 0 ошибок")
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
            self.table.setItem(row, 1, QTableWidgetItem("В очереди"))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self._row_by_id[row_id] = row
        self._downloader.start(items, referer, self._dir)
        self._update_summary()
        return len(items)

    # ---------- обработчики ----------

    def _download_pasted(self) -> None:
        urls = [line.strip() for line in self.paste_box.toPlainText().splitlines() if line.strip()]
        if not urls:
            QMessageBox.information(self, "Image Hunter", "Сначала вставьте ссылки в поле слева.")
            return
        added = self.add_urls(urls)
        if added == 0:
            QMessageBox.information(
                self, "Image Hunter",
                "Новых ссылок нет: они уже скачивались в этой сессии или не являются http(s)-ссылками.",
            )
            return
        if added < len(urls):
            self.summary.setText(f"Добавлено {added} из {len(urls)} — остальные уже были в очереди.")
        self.paste_box.clear()

    def _on_status(self, row_id: int, status: str, detail: str) -> None:
        row = self._row_by_id.get(row_id)
        if row is None:
            return
        status_item = self.table.item(row, 1)
        detail_item = self.table.item(row, 2)
        if status_item is None or detail_item is None:
            return
        status_item.setText(status)
        detail_item.setText(detail)
        detail_item.setToolTip(detail)
        if status == "Скачано":
            self._ok += 1
            self._ok_color(status_item, "#1a7f37")
        elif status == "Ошибка":
            self._fail += 1
            self._ok_color(status_item, "#c62828")
        self._update_summary()

    def _on_batch_finished(self, ok: int, fail: int) -> None:
        self.summary.setText(f"Партия завершена: {ok} скачано, {fail} ошибок. Папка: {self._dir}")

    # ---------- служебное ----------

    @staticmethod
    def _ok_color(item: QTableWidgetItem, color: str) -> None:
        item.setForeground(Qt.green if color == "#1a7f37" else Qt.red)

    def _update_summary(self) -> None:
        total = self.table.rowCount()
        self.summary.setText(f"Всего в списке: {total}  •  скачано: {self._ok}  •  ошибок: {self._fail}")

    def change_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Папка для сохранения", self._dir)
        if not directory:
            return
        self._dir = directory
        self.dir_label.setText(directory)
        store_download_dir(directory)
