"""Вкладка «Мои картинки»: дерево дисков/папок + миниатюры + полноэкранный просмотр с зумом."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import (
    QFileInfo,
    QObject,
    QRunnable,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
)
try:
    from PySide6.QtCore import QStorageInfo
except ImportError:  # в части сборок PySide6 класс живёт в QtGui
    from PySide6.QtGui import QStorageInfo  # type: ignore[no-redef]
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
    QSplitter,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
THUMB = 160
TREE_WIDTH = 230

# виртуальные файловые системы и точки монтирования, которые не показываем в дереве
_VIRTUAL_FS = {
    "proc", "sysfs", "devtmpfs", "tmpfs", "devfs", "ramfs", "squashfs", "overlay",
    "cgroup", "cgroup2", "securityfs", "pstore", "debugfs", "tracefs", "configfs",
    "fusectl", "hugetlbfs", "mqueue", "bpf", "autofs", "binfmt_misc", "efivarfs",
    "virtiofs", "iso9660",
}
_VIRTUAL_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap", "/boot", "/var/lib")


def _fmt_bytes(num: float) -> str:
    value = float(num)
    unit = "Б"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            break
        value /= 1024
    return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"


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
    """Слева дерево дисков/папок, затем лента миниатюр, справа просмотр выбранной картинки."""

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
        self.status = QLabel("Выберите диск или папку в дереве слева, либо «Открыть папку…» (Ctrl+O)")
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

        # --- дерево дисков и папок (левая панель) ---
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemExpanded.connect(self._populate_children)
        self.tree.itemClicked.connect(self._on_tree_clicked)

        tree_panel = QWidget()
        tree_lay = QVBoxLayout(tree_panel)
        tree_lay.setContentsMargins(0, 0, 0, 0)
        tree_lay.setSpacing(0)
        tree_hdr = QHBoxLayout()
        tree_hdr.setContentsMargins(8, 6, 4, 2)
        tree_hdr.addWidget(QLabel("Диски и папки"))
        tree_hdr.addStretch(1)
        btn_refresh = QToolButton()
        btn_refresh.setText("⟳")
        btn_refresh.setToolTip("Обновить список дисков и папок (например, после подключения флешки)")
        btn_refresh.setAutoRaise(True)
        btn_refresh.clicked.connect(lambda: self.refresh_drives())
        tree_hdr.addWidget(btn_refresh)
        tree_lay.addLayout(tree_hdr)
        tree_lay.addWidget(self.tree, 1)

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
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(tree_panel)   # 0: дерево дисков/папок
        self.splitter.addWidget(self.list)    # 1: лента миниатюр
        self.splitter.addWidget(self.scroll)  # 2: просмотр
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, False)
        self.splitter.setSizes([TREE_WIDTH, THUMB + 34, 640])
        layout.addWidget(self.splitter, 1)

        self._thumb_signals = _ThumbSignals()
        self._thumb_signals.ready.connect(self._on_thumb_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)

        self.refresh_drives()
        self._restore_last_folder()

    # ---------- публичное ----------

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка с изображениями", self._folder or "")
        if folder:
            self.load_folder(folder, sync_tree=True)

    def load_folder(self, folder: str, sync_tree: bool = False) -> None:
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

        QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", folder)
        if sync_tree:
            self._sync_tree(folder)

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

    # ---------- дерево дисков и папок ----------

    def refresh_drives(self, include_all: bool = False) -> None:
        """Перечитает диски/устройства и быстрые ссылки (Домой, Изображения)."""
        self.tree.clear()

        home = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)
        pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        if home and os.path.isdir(home):
            self._add_folder_item(None, home, title="🏠 Домой",
                                  icon=QStyle.StandardPixmap.SP_DirHomeIcon)
        if pics and os.path.isdir(pics) and os.path.normpath(pics) != os.path.normpath(home):
            self._add_folder_item(None, pics, title="🖼 Изображения")

        for si in QStorageInfo.mountedVolumes():
            if not si.isValid() or not si.isReady():
                continue
            if not include_all and self._is_virtual(si):
                continue
            self._add_drive_item(si)

    @staticmethod
    def _is_virtual(si) -> bool:
        fstype = bytes(si.fileSystemType()).decode(errors="ignore").lower()
        if fstype in _VIRTUAL_FS or fstype.startswith("fuse."):
            return True
        path = si.rootPath()
        return any(path == p or path.startswith(p + "/") for p in _VIRTUAL_PREFIXES)

    def _add_drive_item(self, si) -> None:
        path = si.rootPath()
        label = si.displayName() or path
        if os.name != "nt" and label == path:
            label = "💾 " + (path if len(path) > 1 else "Диск /")
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        total, free = si.bytesTotal(), si.bytesFree()
        tip = path
        if total > 0:
            tip += f"\nСвободно: {_fmt_bytes(free)} из {_fmt_bytes(total)}"
        item.setToolTip(0, tip)
        item.addChild(self._dummy_item())
        self.tree.addTopLevelItem(item)

    def _add_folder_item(self, parent, path: str, title: str | None = None,
                         icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_DirIcon) -> None:
        item = QTreeWidgetItem([title or os.path.basename(path) or path])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setIcon(0, self.style().standardIcon(icon))
        item.setToolTip(0, path)
        item.addChild(self._dummy_item())
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)

    @staticmethod
    def _dummy_item() -> QTreeWidgetItem:
        marker = QTreeWidgetItem([""])
        marker.setData(0, Qt.ItemDataRole.UserRole, "")
        return marker

    def _populate_children(self, item: QTreeWidgetItem) -> None:
        """Ленивая загрузка подпапок на один уровень при раскрытии."""
        if item.data(0, Qt.ItemDataRole.UserRole + 1):  # уже раскрывали
            return
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        while item.childCount():
            item.removeChild(item.child(0))  # убираем заглушку
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        dir_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        for sub in self._list_subdirs(path):
            child = QTreeWidgetItem([os.path.basename(sub)])
            child.setData(0, Qt.ItemDataRole.UserRole, sub)
            child.setIcon(0, dir_icon)
            child.setToolTip(0, sub)
            child.addChild(self._dummy_item())
            item.addChild(child)

    @staticmethod
    def _list_subdirs(path: str) -> list[str]:
        try:
            names = os.listdir(path)
        except OSError:
            return []
        out = []
        for name in sorted(names, key=natural_key):
            if name.startswith("."):
                continue
            full = os.path.join(path, name)
            try:
                if os.path.isdir(full) and not QFileInfo(full).isHidden():
                    out.append(full)
            except OSError:
                continue
        return out

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._populate_children(item)
        item.setExpanded(True)
        self.load_folder(path)

    def _restore_last_folder(self) -> None:
        last = QSettings("ImageHunter", "ImageHunter").value("viewer/last_folder", "")
        if not (last and os.path.isdir(last)):
            return
        # авто-открытие только для папок разумного размера, чтобы не тормозить запуск
        if 0 < len(list_image_files(last)) <= 2000:
            self.load_folder(last, sync_tree=True)

    @staticmethod
    def _is_under(path_n: str, base_n: str) -> bool:
        """path_n строго внутри base_n (учитывает корни дисков: «/», «C:\»)."""
        base = base_n if base_n.endswith(os.sep) else base_n + os.sep
        return path_n.startswith(base)

    def _sync_tree(self, folder: str) -> None:
        """Раскрывает в дереве путь к folder и подсвечивает её (для «Открыть папку…»)."""
        folder_n = os.path.normpath(folder)
        target = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_n = os.path.normpath(top.data(0, Qt.ItemDataRole.UserRole) or "")
            if top_n == folder_n:
                target = top
                break
            if self._is_under(folder_n, top_n):
                target = self._expand_towards(top, folder_n)
                if target is not None:
                    break
        if target is not None:
            self.tree.setCurrentItem(target)
            self.tree.scrollToItem(target)

    def _expand_towards(self, item: QTreeWidgetItem, folder_n: str):
        self._populate_children(item)
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            child_n = os.path.normpath(child.data(0, Qt.ItemDataRole.UserRole) or "")
            if child_n == folder_n:
                return child
            if self._is_under(folder_n, child_n):
                found = self._expand_towards(child, folder_n)
                if found is not None:
                    return found
        return None

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
