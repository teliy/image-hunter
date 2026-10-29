"""Вкладка «Мои картинки»: миниатюры папки + полноэкранный просмотр с зумом."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QImage,
    QImageReader,
    QKeySequence,
    QMovie,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
THUMB = 160


def natural_key(name: str):
    """Сортировка «по-человечески»: file2 < file10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_image_files(folder: str) -> list[str]:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(
        (os.path.join(folder, n) for n in names
         if os.path.splitext(n)[1].lower() in IMAGE_EXTS and os.path.isfile(os.path.join(folder, n))),
        key=lambda p: natural_key(os.path.basename(p)),
    )


# ---------- фоновые миниатюры ----------

class _ThumbSignals(QObject):
    ready = Signal(int, QImage)  # строка списка, готовая миниатюра


class _ThumbTask(QRunnable):
    def __init__(self, path: str, row: int, signals: _ThumbSignals):
        super().__init__()
        self.path, self.row, self.signals = path, row, signals

    def run(self) -> None:
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            reader.setScaledSize(size.scaled(THUMB, THUMB, Qt.KeepAspectRatio))
        img = reader.read()
        if not img.isNull():
            self.signals.ready.emit(self.row, img)


# ---------- виджет ----------

class LocalViewer(QWidget):
    """Слева сетка миниатюр, справа просмотр выбранной картинки."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._folder = ""
        self._mode = "fit"          # fit | manual
        self._zoom = 1.0
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._thumbs_done = 0

        # --- верхняя панель ---
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)

        def btn(text, tip, slot, shortcut=None):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            if shortcut:
                sc = QShortcut(QKeySequence(shortcut), self)
                sc.activated.connect(slot)
            bar.addWidget(b)
            return b

        btn("📂 Открыть папку…", "Выбрать папку с изображениями (Ctrl+O)", self.open_folder, "Ctrl+O")
        bar.addSpacing(8)
        self.btn_prev = btn("◀", "Предыдущая (Left)", lambda: self.step(-1))
        self.btn_next = btn("▶", "Следующая (Right)", lambda: self.step(+1))
        bar.addSpacing(8)
        btn("−", "Уменьшить", lambda: self.zoom(1 / 1.25))
        btn("100%", "Реальный размер", lambda: self.set_manual_zoom(1.0))
        btn("◱", "Вписать в окно", self.fit_to_window)
        btn("+", "Увеличить", lambda: self.zoom(1.25))
        bar.addSpacing(8)
        btn("🗂 Показать в папке", "Открыть текущую папку в Проводнике", self.reveal_folder)
        bar.addStretch(1)
        self.status = QLabel("Откройте папку с изображениями")
        self.status.setStyleSheet("color: #666;")
        bar.addWidget(self.status)

        # --- список миниатюр ---
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setFixedWidth(THUMB + 34)
        self.list.currentRowChanged.connect(self._show_index)
        self.list.itemDoubleClicked.connect(
            lambda item: QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
        )

        # --- область просмотра ---
        self.view_label = QLabel("…")
        self.view_label.setAlignment(Qt.AlignCenter)
        self.view_label.setBackgroundRole(QPalette.ColorRole.Dark)
        self.view_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.view_label.setScaledContents(False)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.view_label)
        self.scroll.setWidgetResizable(True)
        self.scroll.setBackgroundRole(QPalette.ColorRole.Dark)
        self.scroll.viewport().installEventFilter(self)  # Ctrl+колесо — зум

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.list)
        body.addWidget(self.scroll, 1)
        layout.addLayout(body, 1)

        self._thumb_signals = _ThumbSignals()
        self._thumb_signals.ready.connect(self._on_thumb_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)

    # ---------- публичное ----------

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка с изображениями", self._folder or "")
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder: str) -> None:
        self._folder = folder
        self._paths = list_image_files(folder)
        self.list.clear()
        self._thumbs_done = 0
        self._pixmap = None
        self._movie = None

        placeholder = QPixmap(THUMB, THUMB)
        placeholder.fill(Qt.darkGray)

        for row, path in enumerate(self._paths):
            item = QListWidgetItem(QIcon(placeholder), os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(os.path.basename(path))
            self.list.addItem(item)
            self._pool.start(_ThumbTask(path, row, self._thumb_signals))

        if self._paths:
            self.list.setCurrentRow(0)
        else:
            self.view_label.setText("В этой папке нет изображений")
            self.status.setText(folder or "—")

    # ---------- просмотр ----------

    def step(self, delta: int) -> None:
        if not self._paths:
            return
        row = (self.list.currentRow() + delta) % self.list.count()
        self.list.setCurrentRow(row)

    def _show_index(self, row: int) -> None:
        if not (0 <= row < len(self._paths)):
            return
        path = self._paths[row]
        self._movie = None

        if os.path.splitext(path)[1].lower() == ".gif":
            self._pixmap = None
            self._mode = "fit"
            movie = QMovie(path)
            if movie.isValid():
                self._movie = movie
                self.view_label.setMovie(movie)
                movie.start()
        else:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            img = reader.read()
            if img.isNull():
                self.view_label.setText(f"Не удалось открыть:\n{img.errorString()}")
                return
            self._pixmap = QPixmap.fromImage(img)
            self._apply_mode()

        if self._movie is not None:
            size = self._movie.currentPixmap().size()
        elif self._pixmap is not None:
            size = self._pixmap.size()
        else:
            size = QSize(0, 0)
        self.status.setText(
            f"{os.path.basename(path)}  •  {row + 1} из {len(self._paths)}  •  {size.width()}×{size.height()}"
        )

    # ---------- зум ----------

    def _apply_mode(self) -> None:
        if self._movie is not None or self._pixmap is None:
            return
        if self._mode == "fit":
            area = self.scroll.viewport().size() * 0.96
            scaled = self._pixmap.scaled(
                QSize(int(area.width()), int(area.height())),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        else:
            w = max(1, int(self._pixmap.width() * self._zoom))
            h = max(1, int(self._pixmap.height() * self._zoom))
            scaled = self._pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.view_label.setPixmap(scaled)
        self.view_label.resize(scaled.size())

    def zoom(self, factor: float) -> None:
        if self._pixmap is None:
            return
        self._mode = "manual"
        self._zoom = max(0.05, min(12.0, self._zoom * factor))
        self._apply_mode()

    def set_manual_zoom(self, value: float) -> None:
        if self._pixmap is None:
            return
        self._mode = "manual"
        self._zoom = max(0.05, min(12.0, value))
        self._apply_mode()

    def fit_to_window(self) -> None:
        self._mode = "fit"
        self._apply_mode()

    def reveal_folder(self) -> None:
        if self._folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))

    # ---------- служебное ----------

    def _on_thumb_ready(self, row: int, img: QImage) -> None:
        item = self.list.item(row)
        if item is not None:
            item.setIcon(QIcon(QPixmap.fromImage(img)))
        self._thumbs_done += 1

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._mode == "fit":
            self._apply_mode()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        try:
            from PySide6.QtGui import QWheelEvent  # локальный импорт для читаемости

            if obj is self.scroll.viewport() and isinstance(event, QWheelEvent):
                if event.modifiers() & Qt.ControlModifier:
                    self.zoom(1.25 if event.angleDelta().y() > 0 else 1 / 1.25)
                    return True
        except RuntimeError:
            return False  # объект уже уничтожен (завершение приложения)
        return super().eventFilter(obj, event)
