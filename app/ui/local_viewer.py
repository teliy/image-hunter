"""Вкладка «Мои картинки»: дерево дисков/папок + миниатюры + полноэкранный просмотр с зумом."""

from __future__ import annotations

import hashlib
import math
import os
import random
import re
import shiboken6
import shutil
import stat
import sys
import tempfile
import time

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QElapsedTimer,
    QEvent,
    QFile,
    QObject,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRunnable,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
try:
    from PySide6.QtCore import QStorageInfo
except ImportError:  # в части сборок PySide6 класс живёт в QtGui
    from PySide6.QtGui import QStorageInfo  # type: ignore[no-redef]
from PySide6.QtGui import (
    QBrush,
    QDesktopServices,
    QDrag,
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QMovie,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import applog, i18n, imgload, modstatus, netfs
from app.core.i18n import tr
from app.ui import rembg_manager, upscale_manager, watermark_manager

# .avif добавлен явно: PySide6 не умеет AVIF без Pillow-кодека (см. imgload),
# но сами файлы в ленте показывать надо — декодирует imgload
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".avif", ".avifs"}
THUMB = 160
TREE_WIDTH = 230
THUMB_CACHE_MAX = 256 * 1024 * 1024   # предел кэша миниатюр на диске
_RESTORE_MAX_FILES = 2000   # автопоказ последней папки: больше — только вручную
_TREE_TOKEN_ROLE = Qt.ItemDataRole.UserRole + 2   # жетон фоновой догрузки узла
_TREE_SYNC_ROLE = Qt.ItemDataRole.UserRole + 3    # путь-цель асинхронной прогулки к папке
_TREE_SYNC_SEQ_ROLE = Qt.ItemDataRole.UserRole + 4  # поколение прогулки (для отмены)
_FAV_ROLE = Qt.ItemDataRole.UserRole + 5          # узел — избранная папка (v0.7.9)
_DRIVE_ROLE = Qt.ItemDataRole.UserRole + 6        # узел — диск (v0.7.14)
_FAV_KEY = "viewer/favorites"                     # где лежат избранные папки
_RES_ROLE = Qt.ItemDataRole.UserRole + 10   # подпись плитки: разрешение картинки (v0.8.4)
# tEXt-ключ внутри PNG кэша миниатюр, в котором хранится исходное разрешение:
# при попадании в кэш оригинал не читается вовсе, а подписи разрешение нужно
_DIMS_TEXT_KEY = "ih-dims"

# ---------- изменение размера картинки мышью (v0.8.6) ----------
_RESIZE_HANDLE = 12            # видимый размер рукоятки (угол), px
_RESIZE_EDGE = 6               # толщина краевых рукояток, px
_RESIZE_SLOP = 5               # запас зоны попадания курсора вокруг рукоятки, px
_RESIZE_MIN = 1                # минимальная сторона результата, px
_RESIZE_MAX_SIDE = 16383       # разумный предел стороны (ограничение QImage/текстур)
_RESIZE_MAX_PIXELS = 64_000_000   # предел площади: RGBA-картинка такого размера ≈ 256 МБ
# формат записи результата по расширению оригинала: (Qt-формат, качество | None);
# AVIF средствами Qt не записывается — такой оригинал уезжает в PNG (v0.8.6)
_RESIZE_SAVE_FORMATS = {
    ".png": ("PNG", None), ".jpg": ("JPEG", 92), ".jpeg": ("JPEG", 92),
    ".bmp": ("BMP", None), ".webp": ("WEBP", 90),
    ".tiff": ("TIFF", None), ".tif": ("TIFF", None),
}
_RESIZE_DEFAULT_FMT = ("PNG", None)

# ---------- обрезка картинки мышью, как в XnView (v0.8.7) ----------
_CROP_MIN_DRAG = 4            # движение мыши короче (px виджета) — случайный клик
_CROP_SUFFIX = "crop"         # имя результата: «имя_crop.ext», конфликт → «-1»

# ---------- пипетка и закрашивание выделенной области (v0.8.8) ----------
_FILL_SUFFIX = "fill"         # имя результата: «имя_fill.ext», конфликт → «-1»
_PICKER_HOLD_S = 1.2          # сколько секунд подсказка «цвет в буфере» не гасится наведением


def _free_fill_name(folder: str, stem: str, ext: str) -> str:
    """Свободное имя «stem_fill.ext», затем «stem_fill-1.ext»… — без затираний.

    Вызывается из рабочего потока непосредственно перед записью (v0.8.8):
    если файл с таким именем появился между кликом «Закрасить» и записью,
    результат получает следующий свободный номер — чужой файл не тронут."""
    base = f"{stem}_{_FILL_SUFFIX}"
    candidate = f"{base}{ext}"
    n = 0
    while os.path.lexists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{base}-{n}{ext}"
    return candidate


def _resize_save_ext(ext: str) -> str:
    """Расширение файла-результата по расширению оригинала (AVIF → .png)."""
    return ext.lower() if ext.lower() in _RESIZE_SAVE_FORMATS else ".png"


def _resize_format_for(ext: str) -> tuple[str, int | None]:
    """(Qt-формат, качество) записи результата по расширению оригинала."""
    return _RESIZE_SAVE_FORMATS.get(ext.lower(), _RESIZE_DEFAULT_FMT)


def _clamp_resize(w: int, h: int) -> tuple[int, int]:
    """Ограничить запрошенный размер: стороны — до 16383, площадь — до 64 Мп.

    Верхние пределы защищают и от случайного «растягивания до гигантской
    картинки» (память RGBA ×4 байта), и от пределов самого QImage."""
    w = max(_RESIZE_MIN, min(_RESIZE_MAX_SIDE, int(w)))
    h = max(_RESIZE_MIN, min(_RESIZE_MAX_SIDE, int(h)))
    if w * h > _RESIZE_MAX_PIXELS:
        k = math.sqrt(_RESIZE_MAX_PIXELS / float(w * h))
        w = max(_RESIZE_MIN, int(w * k))
        h = max(_RESIZE_MIN, int(h * k))
    return w, h


def _resize_target_for(handle: int, start: QSize, dx: int, dy: int,
                       orig: QSize) -> QSize:
    """Новый размер по типу рукоятки (v0.8.6).

    Угол — пропорционально исходным пропорциям картинки (за ширину);
    правый край — только ширина, нижний край — только высота. Результат
    всегда в пределах _clamp_resize."""
    if handle == _ResizeView.HANDLE_CORNER:
        w = start.width() + dx
        h = int(round(w * orig.height() / max(1, orig.width())))
    elif handle == _ResizeView.HANDLE_RIGHT:
        w, h = start.width() + dx, start.height()
    elif handle == _ResizeView.HANDLE_BOTTOM:
        w, h = start.width(), start.height() + dy
    else:
        w, h = start.width(), start.height()
    w, h = _clamp_resize(w, h)
    return QSize(w, h)


def _free_resize_name(folder: str, stem: str, w: int, h: int, ext: str) -> str:
    """Свободное имя «stem_WxH.ext», затем «stem_WxH-1.ext»… — без затираний.

    Вызывается из рабочего потока непосредственно перед записью (v0.8.6):
    если файл с таким именем появился между кликом «Сохранить» и записью,
    результат получает следующий свободный номер — чужой файл не тронут."""
    base = f"{stem}_{w}x{h}"
    candidate = f"{base}{ext}"
    n = 0
    while os.path.lexists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{base}-{n}{ext}"
    return candidate


def _free_crop_name(folder: str, stem: str, ext: str) -> str:
    """Свободное имя «stem_crop.ext», затем «stem_crop-1.ext»… — без затираний.

    Вызывается из рабочего потока непосредственно перед записью (v0.8.7):
    если файл с таким именем появился между кликом и записью, результат
    получает следующий свободный номер — чужой файл не тронут."""
    base = f"{stem}_{_CROP_SUFFIX}"
    candidate = f"{base}{ext}"
    n = 0
    while os.path.lexists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{base}-{n}{ext}"
    return candidate


def _dims_text(w: int, h: int) -> str:
    """Разрешение в виде для подписи плитки и для хранения в кэше.

    В кэше — с латинским «x» (1920x1080, парсится одним регэкспом),
    в подписи — с типографским «×», как в статусе просмотра (v0.8.4)."""
    return f"{w}×{h}"


def _dims_from_cache(img: QImage) -> tuple[int, int]:
    """Достать разрешение из tEXt-чанка кэшированной миниатюры (см. _store).

    Чанка нет (старые записи кэша) или он битый — ``(0, 0)``: плитка просто
    рисуется без второй строки, а при следующем декоде чанк появится."""
    try:
        raw = img.text(_DIMS_TEXT_KEY)
    except Exception:                     # noqa: BLE001 — чанк не должен ронять ленту
        return 0, 0
    m = re.fullmatch(r"(\d+)x(\d+)", (raw or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# сетевость дисков уже выясненное (кэш): буква диска -> DRIVE_REMOTE
_REMOTE_DRIVE_CACHE: dict[str, bool] = {}
# наличие корзины по корню диска — тоже кэш: запрос за выделенные 200 файлов
# не должен 200 раз ходить в shell (на сетевом диске каждый не мгновенен)
_TRASH_DRIVE_CACHE: dict[str, bool] = {}

def _is_remote_path(path: str) -> bool:
    """Сетевой ли путь (WebDAV, SMB, NFS…).

    Windows — подключённый диск через GetDriveTypeW (v0.7.2). Linux —
    fstype самой конкретной точки монтирования из /proc/self/mounts
    (v0.8.19, вся механика в app/core/netfs.py): davfs2, rclone, sshfs,
    CIFS, NFS, 9p/WSL, GVFS-пути GNOME. Раньше на Linux все пути
    считались локальными, узкий сетевой пул (v0.7.2) не включался, и
    davfs2 заваливали параллельными запросами — слоты кончались, чтения
    провисали ~30 с и падали с Errno 11 (репорт v0.8.19: маунт
    cloud.mail.ru, все операции «МЕДЛЕННО» по 700–30 000 мс). Чтение
    таких файлов идёт через отдельный узкий пул: когда сервер подвис,
    ждут одна-две задачи, а не весь пул сразу — локальные миниатюры
    продолжают грузиться."""
    if not path:
        return False
    if sys.platform == "win32":
        try:
            root = os.path.splitdrive(os.path.abspath(path))[0]
            if len(root) < 2:
                return False
            remote = _REMOTE_DRIVE_CACHE.get(root)
            if remote is None:
                import ctypes
                remote = ctypes.windll.kernel32.GetDriveTypeW(root + "\\") == 4
                _REMOTE_DRIVE_CACHE[root] = remote
            return remote
        except Exception:                   # noqa: BLE001 — не получилось — считаем локальным
            return False
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        try:
            return netfs.is_remote(path)
        except Exception:                   # noqa: BLE001 — не получилось — считаем локальным
            return False
    return False

# виртуальные файловые системы и точки монтирования, которые не показываем в дереве
_VIRTUAL_FS = {
    "proc", "sysfs", "devtmpfs", "tmpfs", "devfs", "ramfs", "squashfs", "overlay",
    "cgroup", "cgroup2", "securityfs", "pstore", "debugfs", "tracefs", "configfs",
    "fusectl", "hugetlbfs", "mqueue", "bpf", "autofs", "binfmt_misc", "efivarfs",
    "virtiofs", "iso9660",
}
_VIRTUAL_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap", "/boot", "/var/lib")


def _is_virtual_volume(si) -> bool:
    """Виртуальный том (procfs, overlay, /run…) — в дереве дисков не показывать.

    Модульная функция, чтобы звать из рабочего потока (_DrivesTask), где
    класса LocalViewer ещё нет."""
    fstype = bytes(si.fileSystemType()).decode(errors="ignore").lower()
    if fstype in _VIRTUAL_FS or fstype.startswith("fuse."):
        return True
    path = si.rootPath()
    return any(path == p or path.startswith(p + "/") for p in _VIRTUAL_PREFIXES)


def _star_icon() -> QIcon:
    """Золотая звезда избранного: рисуется кодом, чтобы выглядеть одинаково
    во всех темах и на всех ОС (стандартного значка «звезда» в Qt нет)."""
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    points = []
    for i in range(10):   # 5-конечная звезда: вершина/впадина через одну
        r = 7.0 if i % 2 == 0 else 3.0
        a = math.radians(-90 + i * 36)
        points.append(QPointF(8 + r * math.cos(a), 8.6 + r * math.sin(a)))
    p.setPen(QPen(QColor("#8a6100"), 1.0))
    p.setBrush(QColor("#F5B301"))
    p.drawPolygon(QPolygonF(points))
    p.end()
    return QIcon(pm)


def _fmt_bytes(num: float) -> str:
    value = float(num)
    unit_key = "unit.b"
    for unit_key in ("unit.b", "unit.kb", "unit.mb", "unit.gb", "unit.tb"):
        if value < 1024 or unit_key == "unit.tb":
            break
        value /= 1024
    unit = tr(unit_key)
    return f"{value:.0f} {unit}" if unit_key == "unit.b" else f"{value:.1f} {unit}"


def natural_key(name: str):
    """Сортировка «по-человечески»: file2 < file10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _checker_pixmap(path: str, box: int = 132) -> QPixmap | None:
    """Миниатюра результата на «шахматке»: прозрачность видна сразу.

    None — файл не читается как картинка (порчен, нестандартный). Зовётся
    только для локальных файлов: чтение по сети в GUI-потоке запрещено
    (принцип v0.7.2). Клетки — те же, что в просмотре (v0.7.16): белые и
    серые квадраты, размер клетки — из настроек ползунка."""
    try:
        img = QImage(path)
    except Exception:   # noqa: BLE001 — любой сбой читателя — без превью
        return None
    if img is None or img.isNull():
        return None
    cell = _checker_cell_setting()
    pm = QPixmap(box, box)
    p = QPainter(pm)
    for y in range(0, box, cell):
        for x in range(0, box, cell):
            p.fillRect(x, y, cell, cell,
                       QColor(_CHECKER_WHITE) if (x // cell + y // cell) % 2 == 0
                       else QColor(_CHECKER_GRAY))
    scaled = img.scaled(box - 12, box - 12,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    p.drawImage((box - scaled.width()) // 2, (box - scaled.height()) // 2,
                scaled)
    p.end()
    return pm


# --- фон-«шахматка» под прозрачными картинками (v0.7.16) -------------------
# Белые и серые квадраты вместо ровной тёмной заливки — так видно, где
# картинка прозрачна (как «прозрачный холст» в графических редакторах).
# Размер клетки задаётся ползунком на панели и живёт в QSettings.
_CHECKER_WHITE = "#ffffff"
_CHECKER_GRAY = "#c0c0c0"
CHECKER_MIN = 4          # самая мелкая клетка, логических пикселей
CHECKER_MAX = 32         # самая крупная
CHECKER_DEFAULT = 10     # как в превью выбора после удаления фона (v0.7.15)


def _checker_cell_setting() -> int:
    """Размер клетки «шахматки» из настроек; мусор — к дефолту, числа —
    зажимаются в разрешённый диапазон."""
    try:
        v = QSettings("ImageHunter", "ImageHunter").value(
            "viewer/checker_cell", CHECKER_DEFAULT)
        v = int(v)   # нечисловой мусор (PySide6 с type=int тихо даёт 0) — честный ValueError
    except (TypeError, ValueError):
        return CHECKER_DEFAULT
    return max(CHECKER_MIN, min(CHECKER_MAX, v))


def _checker_tile(cell: int, dpr: float = 1.0) -> QPixmap:
    """Плитка «шахматки» 2×2 клетки — растянется кистью на весь просмотр.

    Левый верхний квадрат белый, по диагонали — серый (как в превью
    выбора v0.7.15). Рисуется в физических пикселях (cell × dpr) и
    помечается devicePixelRatio: на HiDPI-экранах квадраты остаются
    резкими и логического размера."""
    dpr = max(1.0, float(dpr) or 1.0)
    s = max(2, int(round(cell * dpr)))
    pm = QPixmap(s * 2, s * 2)
    pm.fill(QColor(_CHECKER_GRAY))
    p = QPainter(pm)
    p.fillRect(0, 0, s, s, QColor(_CHECKER_WHITE))
    p.fillRect(s, s, s, s, QColor(_CHECKER_WHITE))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _tile_log_points(total: int) -> set[int]:
    """Плитки, о которых журнал пишет «✨ …»: первая, последняя и четверти.

    Репорт v0.8.25: улучшение шло 11 минут — и ни одной строки в журнале,
    не видно, жив ли процесс (плитки были в строке статуса, но журнал —
    главный диагностический канал, по нему присылают репорты). Чистая
    функция — точка проверок в тестах.
    """
    if total <= 0:
        return set()
    marks = {1, total}
    if total > 4:
        marks.update(range(1, total + 1, max(2, total // 4)))
    return marks


def _mini_checker_icon(size: int = 16, cell: int = 4) -> QPixmap:
    """Маленькая шахматка — иконка у ползунка размера клеток."""
    pm = QPixmap(size, size)
    pm.fill(QColor(_CHECKER_WHITE))
    p = QPainter(pm)
    for y in range(0, size, cell):
        for x in range(0, size, cell):
            if (x // cell + y // cell) % 2:
                p.fillRect(x, y, cell, cell, QColor(_CHECKER_GRAY))
    p.end()
    return pm


class _CheckerView(QLabel):
    """QLabel области просмотра с фоном-«шахматкой» (v0.7.16).

    Плитка рисуется ПЕРЕД обычной отрисовкой QLabel — картинка, кадр
    анимации (GIF) и текст ошибок ложатся поверх квадратов. Плитка None —
    обычный QLabel: непрозрачным картинкам (JPEG и т.п.) шахматка не
    показывается вовсе. Узоры отсчитываются от начала виджета-картинки,
    поэтому при прокрутке квадраты едут вместе с ней, как холст."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._tile: QPixmap | None = None

    def set_checker_tile(self, tile: QPixmap | None) -> None:
        self._tile = tile
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._tile is not None and not self._tile.isNull():
            p = QPainter(self)
            p.fillRect(self.rect(), QBrush(self._tile))
        super().paintEvent(event)


class _ResizeView(_CheckerView):
    """Область просмотра с рукоятками изменения размера картинки (v0.8.6).

    В обычном режиме ведёт себя в точности как _CheckerView (шахматка под
    прозрачными картинками, кадр GIF, текст ошибок). В режиме ресайза
    (его включает вьюер) поверх картинки рисуется рамка и три рукоятки:
    угол (пропорционально), правый край (ширина) и нижний край (высота);
    курсор подсказывает, за что можно тянуть, а перетаскивание вьюером
    транслируется в сигналы — математику размера считает LocalViewer
    (_resize_target_for), он же перестраивает показанный пиксмап.
    """

    HANDLE_NONE = 0
    HANDLE_CORNER = 1    # правый-нижний угол: пропорционально
    HANDLE_RIGHT = 2     # правый край: только ширина
    HANDLE_BOTTOM = 3    # нижний край: только высота

    # рукоятки выделения обрезки (v0.8.7): четыре угла, четыре края,
    # перенос рамки и рисование новой — что под курсором при нажатии
    CROP_NONE = 0
    CROP_TL = 1
    CROP_TR = 2
    CROP_BR = 3
    CROP_BL = 4
    CROP_L = 5
    CROP_R = 6
    CROP_T = 7
    CROP_B = 8
    CROP_MOVE = 9
    CROP_DRAW = 10

    resize_started = Signal(int)        # рукоятка захвачена (номер рукоятки)
    resize_dragged = Signal(int, int)   # смещение мыши от точки захвата, px
    resize_finished = Signal()          # кнопка отпущена
    crop_selection_changed = Signal()   # выделение обрезки изменилось (v0.8.7)
    picker_pick = Signal(QPoint)        # цвет взят: пиксель картинки (v0.8.8)
    picker_hover = Signal(QPoint, bool) # мышь над картинкой: пиксель и «внутри ли» (v0.8.8)

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._resize_on = False
        self._drag_handle = self.HANDLE_NONE
        self._press_pos = QPointF()
        self._badge = ""
        # обрезка (v0.8.7): выделение хранится в КООРДИНАТАХ КАРТИНКИ —
        # не зависит ни от зума, ни от размера окна; None — выделения нет
        self._crop_on = False
        self._crop_sel: QRect | None = None
        self._crop_img = QSize(0, 0)      # размер картинки в пикселях
        self._crop_drag = self.CROP_NONE
        self._crop_anchor = QPoint()      # якорь резинки/переноса (картинка)
        self._crop_sel0 = QRect()         # выделение на момент захвата
        self._crop_press_w = QPointF()    # точка нажатия (виджет) — отсчёт драга
        # пипетка (v0.8.8): в режиме курсор-крестик над картинкой, клик берёт
        # цвет; ПРАВЫЙ клик берёт цвет в любом режиме (без входа в режимы)
        self._picker_on = False
        # mouseTracking: курсор-подсказка «за что тянуть» без зажатой кнопки
        self.setMouseTracking(True)

    # ---------- состояние режима (управляет LocalViewer) ----------

    def set_resize_mode(self, on: bool) -> None:
        self._resize_on = bool(on)
        self._drag_handle = self.HANDLE_NONE
        if not on:
            self.unsetCursor()
        self.update()

    def set_size_badge(self, text: str) -> None:
        """Бейдж с текущим размером у угла рамки (пусто — не рисовать)."""
        if text != self._badge:
            self._badge = text
            self.update()

    # ---------- режим обрезки (v0.8.7) ----------

    def set_crop_mode(self, on: bool, img_size: QSize | None = None) -> None:
        self._crop_on = bool(on)
        self._crop_drag = self.CROP_NONE
        self._crop_sel = None
        if img_size is not None:
            self._crop_img = QSize(img_size)
        if not on:
            self.unsetCursor()
        self.update()

    # ---------- режим пипетки (v0.8.8) ----------

    def set_picker_mode(self, on: bool) -> None:
        self._picker_on = bool(on)
        if not on:
            self.unsetCursor()
        self.update()

    def set_img_size(self, size: QSize) -> None:
        """Запомнить размер показанной картинки в пикселях.

        Нужно пипетке: правый клик берёт цвет в ЛЮБОМ режиме, без входа
        в режимы обрезки/пипетки, — значит, размер картинки у вью всегда
        актуальный. Тот же размер использует и обрезка (_crop_img)."""
        self._crop_img = QSize(size)

    def has_selection(self) -> bool:
        """Есть ли выделенная область обрезки."""
        return self._crop_sel is not None and not self._crop_sel.isNull()

    def selection(self) -> QRect:
        """Выделенная область в координатах КАРТИНКИ (QRect() — нет выделения).

        Именно этот прямоугольник уходит в _CropSaveTask: координаты
        картинки не зависят от зума показа — что выделено, то и запишется."""
        return QRect(self._crop_sel) if self._crop_sel else QRect()

    # ---------- геометрия ----------

    def pixmap_rect(self) -> QRect:
        """Прямоугольник картинки внутри виджета (QLabel центрует содержимое)."""
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return QRect()
        x = max(0, (self.width() - pm.width()) // 2)
        y = max(0, (self.height() - pm.height()) // 2)
        return QRect(x, y, pm.width(), pm.height())

    def _corner_rect(self, r: QRect) -> QRect:
        return QRect(r.right() - _RESIZE_HANDLE + 1, r.bottom() - _RESIZE_HANDLE + 1,
                     _RESIZE_HANDLE, _RESIZE_HANDLE)

    def _right_rect(self, r: QRect) -> QRect:
        return QRect(r.right() - _RESIZE_EDGE // 2,
                     (r.top() + r.bottom()) // 2 - _RESIZE_HANDLE,
                     _RESIZE_EDGE, _RESIZE_HANDLE * 2)

    def _bottom_rect(self, r: QRect) -> QRect:
        return QRect((r.left() + r.right()) // 2 - _RESIZE_HANDLE,
                     r.bottom() - _RESIZE_EDGE // 2,
                     _RESIZE_HANDLE * 2, _RESIZE_EDGE)

    def handle_at(self, pos) -> int:
        """Какая рукоятка под точкой (с запасом _RESIZE_SLOP), 0 — никакая."""
        r = self.pixmap_rect()
        if r.isNull():
            return self.HANDLE_NONE
        slop = _RESIZE_SLOP
        if self._corner_rect(r).adjusted(-slop, -slop, slop, slop).contains(pos):
            return self.HANDLE_CORNER
        if self._right_rect(r).adjusted(-slop, -slop, slop, slop).contains(pos):
            return self.HANDLE_RIGHT
        if self._bottom_rect(r).adjusted(-slop, -slop, slop, slop).contains(pos):
            return self.HANDLE_BOTTOM
        return self.HANDLE_NONE

    def _cursor_for(self, handle: int) -> Qt.CursorShape:
        if handle == self.HANDLE_CORNER:
            return Qt.CursorShape.SizeFDiagCursor
        if handle == self.HANDLE_RIGHT:
            return Qt.CursorShape.SizeHorCursor
        if handle == self.HANDLE_BOTTOM:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    # ---------- геометрия обрезки (v0.8.7) ----------

    def _to_img(self, p: QPointF) -> QPoint:
        """Точка виджета → пиксель картинки, зажатый в пределы картинки."""
        r = self.pixmap_rect()
        if r.isNull() or self._crop_img.isEmpty():
            return QPoint(0, 0)
        x = (p.x() - r.x()) * self._crop_img.width() / max(1, r.width())
        y = (p.y() - r.y()) * self._crop_img.height() / max(1, r.height())
        return QPoint(max(0, min(self._crop_img.width() - 1, int(round(x)))),
                      max(0, min(self._crop_img.height() - 1, int(round(y)))))

    def _sel_widget(self) -> QRect:
        """Выделение в координатах виджета — для рисования и попаданий мыши."""
        r = self.pixmap_rect()
        if r.isNull() or not self._crop_sel:
            return QRect()
        fx = r.width() / max(1, self._crop_img.width())
        fy = r.height() / max(1, self._crop_img.height())
        return QRect(r.x() + int(round(self._crop_sel.x() * fx)),
                     r.y() + int(round(self._crop_sel.y() * fy)),
                     max(1, int(round(self._crop_sel.width() * fx))),
                     max(1, int(round(self._crop_sel.height() * fy))))

    def _clamp_sel(self, sel: QRect) -> QRect:
        """Зажать выделение в пределы картинки, минимум 1×1 пиксель."""
        iw, ih = max(1, self._crop_img.width()), max(1, self._crop_img.height())
        w = max(1, min(iw, sel.width()))
        h = max(1, min(ih, sel.height()))
        x = max(0, min(iw - w, sel.x()))
        y = max(0, min(ih - h, sel.y()))
        return QRect(x, y, w, h)

    def _crop_handle_rect(self, handle: int, s: QRect) -> QRect:
        """Прямоугольник рукоятки выделения в координатах виджета."""
        k = _RESIZE_HANDLE
        mid_x, mid_y = (s.left() + s.right()) // 2, (s.top() + s.bottom()) // 2
        if handle == self.CROP_TL:
            return QRect(s.left() - k // 2, s.top() - k // 2, k, k)
        if handle == self.CROP_TR:
            return QRect(s.right() - k // 2, s.top() - k // 2, k, k)
        if handle == self.CROP_BR:
            return QRect(s.right() - k // 2, s.bottom() - k // 2, k, k)
        if handle == self.CROP_BL:
            return QRect(s.left() - k // 2, s.bottom() - k // 2, k, k)
        if handle == self.CROP_L:
            return QRect(s.left() - k // 2, mid_y - k // 2, k, k)
        if handle == self.CROP_R:
            return QRect(s.right() - k // 2, mid_y - k // 2, k, k)
        if handle == self.CROP_T:
            return QRect(mid_x - k // 2, s.top() - k // 2, k, k)
        return QRect(mid_x - k // 2, s.bottom() - k // 2, k, k)   # CROP_B

    def crop_handle_at(self, pos) -> int:
        """Какая рукоятка выделения под точкой (с запасом _RESIZE_SLOP)."""
        s = self._sel_widget()
        if s.isNull():
            return self.CROP_NONE
        slop = _RESIZE_SLOP
        for h in (self.CROP_TL, self.CROP_TR, self.CROP_BR, self.CROP_BL,
                  self.CROP_L, self.CROP_R, self.CROP_T, self.CROP_B):
            if self._crop_handle_rect(h, s).adjusted(-slop, -slop, slop, slop).contains(pos):
                return h
        return self.CROP_NONE

    def _crop_cursor_for(self, handle: int) -> Qt.CursorShape:
        m = {self.CROP_TL: Qt.CursorShape.SizeFDiagCursor,
             self.CROP_BR: Qt.CursorShape.SizeFDiagCursor,
             self.CROP_TR: Qt.CursorShape.SizeBDiagCursor,
             self.CROP_BL: Qt.CursorShape.SizeBDiagCursor,
             self.CROP_L: Qt.CursorShape.SizeHorCursor,
             self.CROP_R: Qt.CursorShape.SizeHorCursor,
             self.CROP_T: Qt.CursorShape.SizeVerCursor,
             self.CROP_B: Qt.CursorShape.SizeVerCursor,
             self.CROP_MOVE: Qt.CursorShape.SizeAllCursor,
             self.CROP_DRAW: Qt.CursorShape.CrossCursor}
        return m.get(handle, Qt.CursorShape.ArrowCursor)

    def _crop_hover_cursor(self, pos) -> None:
        """Курсор-подсказка без зажатой кнопки: тяни / переноси / рисуй."""
        if self._crop_drag:
            return
        h = self.crop_handle_at(pos)
        if h:
            self.setCursor(self._crop_cursor_for(h))
        elif self._crop_sel and self._sel_widget().contains(pos):
            self.setCursor(self._crop_cursor_for(self.CROP_MOVE))
        elif self.pixmap_rect().contains(pos):
            self.setCursor(self._crop_cursor_for(self.CROP_DRAW))
        else:
            self.unsetCursor()

    # ---------- мышь ----------

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        # правый клик по картинке — взять цвет пипеткой в ЛЮБОМ режиме
        # (v0.8.8): образец нужен «🪣 Закрасить», а выходить из обрезки
        # ради одного клика неудобно. В режиме ресайса показ не совпадает
        # с картинкой (WYSIWYG целевого размера) — координаты бы соврали
        pr = self.pixmap_rect()
        if (ev.button() == Qt.MouseButton.RightButton and not self._resize_on
                and not pr.isNull() and pr.contains(ev.position().toPoint())):
            self.picker_pick.emit(self._to_img(ev.position()))
            ev.accept()
            return
        if self._picker_on and ev.button() == Qt.MouseButton.LeftButton:
            # клик в режиме пипетки — взять цвет (v0.8.8)
            pr = self.pixmap_rect()
            if not pr.isNull() and pr.contains(ev.position().toPoint()):
                self.picker_pick.emit(self._to_img(ev.position()))
                ev.accept()
                return
        if self._crop_on and ev.button() == Qt.MouseButton.LeftButton:
            pr = self.pixmap_rect()
            if not pr.isNull() and pr.contains(ev.position().toPoint()):
                had_sel = self.has_selection()
                h = self.crop_handle_at(ev.position().toPoint())
                if h:
                    self._crop_drag = h          # тянем рукоятку
                elif had_sel and self._sel_widget().contains(ev.position().toPoint()):
                    self._crop_drag = self.CROP_MOVE   # переносим рамку
                else:
                    self._crop_drag = self.CROP_DRAW   # рисуем новую рамку
                    self._crop_sel = None
                self._crop_press_w = ev.position()
                self._crop_anchor = self._to_img(ev.position())
                self._crop_sel0 = QRect(self._crop_sel) if self._crop_sel else QRect()
                self.setCursor(self._crop_cursor_for(self._crop_drag))
                self.update()
                if had_sel and not self._crop_sel:
                    self.crop_selection_changed.emit()   # старое выделение сброшено
                ev.accept()
                return
        if self._resize_on and ev.button() == Qt.MouseButton.LeftButton:
            handle = self.handle_at(ev.position().toPoint())
            if handle:
                self._drag_handle = handle
                self._press_pos = ev.position()
                self.setCursor(self._cursor_for(handle))
                self.resize_started.emit(handle)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._crop_on and self._crop_drag:
            img_p = self._to_img(ev.position())
            full = QRect(0, 0, self._crop_img.width(), self._crop_img.height())
            if self._crop_drag == self.CROP_DRAW:
                # резинка: от якоря до текущего пикселя включительно, в пределах картинки
                sel = QRect(QPoint(min(self._crop_anchor.x(), img_p.x()),
                                   min(self._crop_anchor.y(), img_p.y())),
                            QPoint(max(self._crop_anchor.x(), img_p.x()),
                                   max(self._crop_anchor.y(), img_p.y())))
                if not full.isNull():
                    sel = sel.intersected(full)
            elif self._crop_drag == self.CROP_MOVE:
                dx = img_p.x() - self._crop_anchor.x()
                dy = img_p.y() - self._crop_anchor.y()
                sel = self._clamp_sel(self._crop_sel0.translated(dx, dy))
            else:
                sel = self._crop_resize_sel(self._crop_sel0, self._crop_drag, img_p)
            if sel != self._crop_sel:
                self._crop_sel = sel
                self.crop_selection_changed.emit()
            self.update()
            ev.accept()
            return
        if self._crop_on:
            self._crop_hover_cursor(ev.position().toPoint())
            super().mouseMoveEvent(ev)
            return
        if self._picker_on:
            # живое чтение цвета под курсором (v0.8.8): статус вьюера
            pr = self.pixmap_rect()
            if not pr.isNull() and pr.contains(ev.position().toPoint()):
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.picker_hover.emit(self._to_img(ev.position()), True)
            else:
                self.unsetCursor()
                self.picker_hover.emit(QPoint(), False)
            super().mouseMoveEvent(ev)
            return
        if self._drag_handle:
            d = ev.position() - self._press_pos
            self.resize_dragged.emit(int(round(d.x())), int(round(d.y())))
            ev.accept()
            return
        if self._resize_on:
            self.setCursor(self._cursor_for(self.handle_at(ev.position().toPoint())))
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if (self._crop_on and self._crop_drag
                and ev.button() == Qt.MouseButton.LeftButton):
            was_draw = self._crop_drag == self.CROP_DRAW
            # движение короче _CROP_MIN_DRAG — случайный клик, не выделение
            moved = ((ev.position() - self._crop_press_w).manhattanLength()
                     >= _CROP_MIN_DRAG)
            self._crop_drag = self.CROP_NONE
            if was_draw and not moved:
                self._crop_sel = None
            self._crop_hover_cursor(ev.position().toPoint())
            self.crop_selection_changed.emit()
            self.update()
            ev.accept()
            return
        if self._drag_handle and ev.button() == Qt.MouseButton.LeftButton:
            self._drag_handle = self.HANDLE_NONE
            self.resize_finished.emit()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ((self._resize_on or self._crop_on or self._picker_on)
                and not self._drag_handle and not self._crop_drag):
            self.unsetCursor()
        super().leaveEvent(ev)

    def _crop_resize_sel(self, s0: QRect, handle: int, p: QPoint) -> QRect:
        """Выделение с подвинутой рукояткой: угол тянет два края, край — один.

        Считается от выделения на момент захвата (s0), поэтому «прош MouseEvent»
        через противоположную сторону просто переворачивает рамку, без накопления
        ошибки. Результат зажат в пределы картинки, сторона — минимум 1 px."""
        l, t = s0.left(), s0.top()
        r, b = s0.right(), s0.bottom()
        if handle in (self.CROP_TL, self.CROP_L, self.CROP_BL):
            l = p.x()
        if handle in (self.CROP_TR, self.CROP_R, self.CROP_BR):
            r = p.x()
        if handle in (self.CROP_TL, self.CROP_T, self.CROP_TR):
            t = p.y()
        if handle in (self.CROP_BL, self.CROP_B, self.CROP_BR):
            b = p.y()
        sel = QRect(QPoint(min(l, r), min(t, b)), QPoint(max(l, r), max(t, b)))
        return self._clamp_sel(sel)

    # ---------- отрисовка ----------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)   # шахматка + картинка/кадр/текст (v0.7.16)
        if self._crop_on:
            self._paint_crop()
            return   # режимы взаимоисключающие: в обрезке рамки ресайса нет
        if not self._resize_on:
            return
        r = self.pixmap_rect()
        if r.isNull():
            return
        p = QPainter(self)
        # рамка вокруг картинки результата — видно, ЧТО именно сохранится
        p.setPen(QPen(QColor(255, 255, 255, 150), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))
        # рукоятки — тем же янтарным, что звезда избранного и галочки выдачи
        p.setPen(QPen(QColor("#8a6100"), 1.0))
        p.setBrush(QColor("#F5B301"))
        p.drawRect(self._corner_rect(r).adjusted(0, 0, -1, -1))
        p.drawRect(self._right_rect(r).adjusted(0, 0, -1, -1))
        p.drawRect(self._bottom_rect(r).adjusted(0, 0, -1, -1))
        # бейдж с текущим размером — под правым-нижним углом рамки
        if self._badge:
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(self._badge) + 12, fm.height() + 4
            bx = min(self.width() - tw, r.right() - tw + _RESIZE_HANDLE)
            by = r.bottom() + 4
            if by + th > self.height():
                by = max(0, r.top() - th - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(int(bx), int(by), tw, th, 3, 3)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRect(int(bx), int(by), tw, th).adjusted(6, 2, -6, -2),
                       Qt.AlignmentFlag.AlignCenter, self._badge)
        p.end()

    def _paint_crop(self) -> None:
        """Выделение обрезки (v0.8.7) — как в XnView: затемнение вне рамки,

        внутри — сетка третей; рамка двойная (белая сплошная + чёрный
        пунктир со сдвигом) — видна на любом фоне; восемь янтарных рукояток
        (тем же цветом, что в режиме размера) и бейдж с размером выделения."""
        r = self.pixmap_rect()
        if r.isNull():
            return
        s = self._sel_widget()
        p = QPainter(self)
        if not s.isNull():
            # затемнение вне выделения — четыре полосы внутри картинки
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            for band in (QRect(r.left(), r.top(), r.width(),
                               max(0, s.top() - r.top())),
                         QRect(r.left(), s.bottom() + 1, r.width(),
                               max(0, r.bottom() - s.bottom())),
                         QRect(r.left(), s.top(),
                               max(0, s.left() - r.left()), s.height()),
                         QRect(s.right() + 1, s.top(),
                               max(0, r.right() - s.right()), s.height())):
                if band.width() > 0 and band.height() > 0:
                    p.drawRect(band)
            # сетка третей внутри выделения — на достаточно больших рамках
            if s.width() >= 30 and s.height() >= 30:
                p.setPen(QPen(QColor(255, 255, 255, 80), 1))
                for i in (1, 2):
                    x = s.left() + s.width() * i // 3
                    p.drawLine(x, s.top() + 1, x, s.bottom() - 1)
                    y = s.top() + s.height() * i // 3
                    p.drawLine(s.left() + 1, y, s.right() - 1, y)
            # рамка: чёрный пунктир со сдвигом + белая сплошная поверх
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 170), 1, Qt.PenStyle.DashLine))
            p.drawRect(s.adjusted(1, 1, 0, 0))
            p.setPen(QPen(QColor(255, 255, 255, 230), 1))
            p.drawRect(s.adjusted(0, 0, -1, -1))
            # восемь рукояток — тем же янтарным, что звезда избранного
            p.setPen(QPen(QColor("#8a6100"), 1.0))
            p.setBrush(QColor("#F5B301"))
            for h in (self.CROP_TL, self.CROP_TR, self.CROP_BR, self.CROP_BL,
                      self.CROP_L, self.CROP_R, self.CROP_T, self.CROP_B):
                p.drawRect(self._crop_handle_rect(h, s).adjusted(0, 0, -1, -1))
            # бейдж с размером выделения — под правым-нижним углом рамки
            badge = f"{self._crop_sel.width()}×{self._crop_sel.height()}"
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(badge) + 12, fm.height() + 4
            bx = min(self.width() - tw, s.right() - tw + _RESIZE_HANDLE)
            by = s.bottom() + 4
            if by + th > self.height():
                by = max(0, s.top() - th - 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(int(bx), int(by), tw, th, 3, 3)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRect(int(bx), int(by), tw, th).adjusted(6, 2, -6, -2),
                       Qt.AlignmentFlag.AlignCenter, badge)
        p.end()


def _is_hidden_entry(entry: os.DirEntry) -> bool:
    """Скрытый ли элемент — только по данным scandir, без лишних stat() (важно для сети)."""
    if entry.name.startswith("."):
        return True
    if os.name == "nt":
        try:
            # на Windows stat(follow_symlinks=False) бесплатный: данные уже
            # получены при перечислении каталога (FindFirstFile/FindNextFile)
            attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        except OSError:
            return False
        if attrs & 0x2:  # FILE_ATTRIBUTE_HIDDEN
            return True
    return False


def scan_image_entries(folder: str) -> list[tuple[str, int, float]]:
    """[(путь, размер, mtime)] картинок в папке — ОДИН проход os.scandir.

    Ключевое для сетевых дисков: никаких os.path.isfile()/stat() на каждый
    файл — и тип файла, и размер, и время уже лежат в выгрузке каталога.
    Каждый отдельный stat() по SMB — это сетевой round-trip.
    """
    out: list[tuple[str, int, float]] = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                if os.path.splitext(entry.name)[1].lower() not in IMAGE_EXTS:
                    continue
                try:
                    if not entry.is_file():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                out.append((entry.path, st.st_size, st.st_mtime))
    except OSError:
        return []
    out.sort(key=lambda t: natural_key(os.path.basename(t[0])))
    return out


def list_image_files(folder: str) -> list[str]:
    return [p for p, _size, _mtime in scan_image_entries(folder)]


# ---------- удаление: корзина, а на дисках без неё — окончательно ----------

def _drive_has_trash(path: str) -> bool | None:
    """Есть ли на диске с этим файлом корзина (None — неизвестно).

    Сетевые и часть съёмных дисков корзины не имеют — там moveToTrash
    всегда падает, и честнее сразу спрашивать про окончательное удаление.
    Windows: отказ корзины спрашивает SHQueryRecycleBinW (0 — корзина
    есть). Linux (v0.8.19): корзина freedesktop живёт в скрытой папке НА
    ТОМ ЖЕ диске — на davfs2 и прочих сетевых FUSE-маунтах её нет (mkdir
    .Trash-<uid> в WebDAV сервера не делает), поэтому сетевые пути
    отвечают False: приложение сразу предлагает окончательное удаление
    вместо гарантированно неудачной попытки корзины и второго диалога."""
    if sys.platform == "win32" and path:
        try:
            import ctypes
            from ctypes import wintypes

            class _RBInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD),
                            ("i64Size", ctypes.c_int64),
                            ("i64NumItems", ctypes.c_int64)]

            root = os.path.splitdrive(path)[0]
            if len(root) < 2:          # относительный путь или что-то странное
                return None
            cached = _TRASH_DRIVE_CACHE.get(root)
            if cached is not None:
                return cached          # один запрос на диск за всю сессию (v0.7.11)
            info = _RBInfo()
            info.cbSize = ctypes.sizeof(info)
            hr = ctypes.windll.shell32.SHQueryRecycleBinW(root + "\\",
                                                          ctypes.byref(info))
            _TRASH_DRIVE_CACHE[root] = (hr == 0)
            return _TRASH_DRIVE_CACHE[root]
        except Exception:              # noqa: BLE001 — не удалось выяснить
            return None                # (не кэшируем — попробуем в следующий раз)
    if sys.platform == "linux" and path:
        try:
            return not netfs.is_remote(path)
        except Exception:              # noqa: BLE001 — неизвестно
            return None
    return None


def _remove_forever(path: str) -> tuple[bool, str]:
    """Удалить файл окончательно.

    Windows: сначала снимаем «только чтение» — скачанные webp бывают
    read-only, и remove падает из-за атрибута. POSIX (v0.8.19): chmod
    S_IWRITE — это 0o200 (только запись, без чтения) — так мы ломали
    права на файл («что-то с правами», репорт v0.8.19); на POSIX удаление
    зависит от прав на КАТАЛОГ, а не на файл, поэтому владельцу лишь
    добавляется запись, если её не было, — биты никогда не отнимаются.
    EAGAIN (davfs2 при исчерпании слотов запросов) повторяется после
    короткой паузы; PermissionError поясняется подсказкой про маунт."""
    try:
        if not os.path.isfile(path):
            return False, tr("viewer.del_missing")
        try:
            if os.name == "nt":
                os.chmod(path, stat.S_IWRITE)
            else:
                mode = os.stat(path).st_mode
                if not (mode & stat.S_IWUSR):
                    os.chmod(path, mode | stat.S_IWUSR)
        except OSError:
            pass   # атрибут не критичен — попробуем удалить как есть
        try:
            os.remove(path)
            return True, ""
        except OSError as exc:
            if netfs.is_eagain(exc):   # davfs2: слоты заняты — слот освободился, повторим
                time.sleep(0.4)
                try:
                    os.remove(path)
                    return True, ""
                except OSError as retry_exc:
                    exc = retry_exc
            f = QFile(path)        # запасной путь средствами Qt
            if f.remove():
                return True, ""
            msg = f.errorString() or str(exc)
            if isinstance(exc, PermissionError):
                msg += " — " + tr("viewer.del_denied_hint")
            return False, msg
    except Exception as exc:       # noqa: BLE001 — причина уйдёт в журнал
        return False, str(exc)


def _trash_file(path: str) -> tuple[bool, str]:
    """Перенести файл в корзину средствами Qt (вызывается из рабочего потока)."""
    try:
        if not os.path.isfile(path):
            return False, tr("viewer.del_missing")
        res = QFile.moveToTrash(path)
        # PySide6 может вернуть bool или (bool, новый путь) — сминаем оба вида
        ok = bool(res[0]) if isinstance(res, tuple) else bool(res)
        return ok, "" if ok else tr("viewer.del_failed")
    except Exception as exc:       # noqa: BLE001
        return False, str(exc)


# ---------- фоновые миниатюры с постоянным кэшем на диске ----------

class _ThumbSignals(QObject):
    # поколение папки, строка списка, готовая миниатюра,
    # исходное разрешение картинки (0, 0 — если узнать не удалось, v0.8.4)
    ready = Signal(int, int, QImage, int, int)


def _thumb_cache_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    d = os.path.join(base or tempfile.gettempdir(), "ImageHunter", "thumbs")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return ""


def _thumb_cache_key(path: str, size: int, mtime: float) -> str:
    # путь + размер + mtime: ключ меняется, когда файл перезаписан.
    # v2 (0.8.4): внутри кэшированного PNG теперь хранится исходное
    # разрешение (tEXt-чанк, см. _ThumbTask._store). Старые записи его не
    # содержат — смена ключа один раз перекодирует кэш, и подписи с
    # разрешением появляются у всех; записи до v2 доочистятся сами:
    # они самые старые, их первой косит _prune_thumb_cache.
    try:
        norm = os.path.normcase(os.path.abspath(path))
    except OSError:
        norm = path
    raw = f"v2|{norm}|{size}|{mtime:.0f}".encode("utf-8", "surrogateescape")
    return hashlib.sha1(raw).hexdigest()


def _prune_thumb_cache(cache_dir: str, max_bytes: int = THUMB_CACHE_MAX) -> None:
    """Кэш миниатюр не должен расти бесконечно: удаляем самые старые файлы."""
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    items: list[tuple[float, int, str]] = []
    total = 0
    for name in names:
        p = os.path.join(cache_dir, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        total += st.st_size
        items.append((st.st_mtime, st.st_size, p))
    if total <= max_bytes:
        return
    limit = int(max_bytes * 0.8)
    for _mtime, size, p in sorted(items):
        if total <= limit:
            break
        try:
            os.remove(p)
            total -= size
        except OSError:
            pass


class _ThumbTask(QRunnable):
    """Миниатюра: сначала кэш на локальном диске (мгновенно), при промахе —
    чтение файла в фоновом потоке и сохранение в кэш. Повторное открытие
    папки (в том числе сетевой) больше не перечитывает файлы по сети."""

    def __init__(self, path: str, row: int, gen: int, signals: _ThumbSignals,
                 cache_dir: str, size: int = 0, mtime: float = 0.0):
        super().__init__()
        self.path = path
        self.row = row
        self.gen = gen
        self.signals = signals
        self.cache_dir = cache_dir
        self.size = size
        self.mtime = mtime

    def run(self) -> None:
        t0 = time.perf_counter()
        cache_hit = False
        img = None
        w = h = 0
        cache_path = ""
        if self.cache_dir:
            key = _thumb_cache_key(self.path, self.size, self.mtime)
            cache_path = os.path.join(self.cache_dir, key + ".png")
            cached = imgload.load_cached_image(cache_path)   # под замком Qt-декода (v0.8.19)
            if not cached.isNull():
                cache_hit = True
                img = cached
                w, h = _dims_from_cache(cached)   # разрешение едет в самом PNG
        if img is None:
            loaded, _err, w, h = imgload.load_file_ex(self.path, max_side=THUMB)
            img = loaded
            if not img.isNull() and cache_path:
                self._store(cache_path, img, w, h)
        if img.isNull():
            return
        self.signals.ready.emit(self.gen, self.row, img, w, h)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= 400:   # долгое чтение/декодирование файла (сеть, большой файл) — в журнал
            applog.slow_event(tr("perf.op.thumb_decode", name=os.path.basename(self.path)),
                              ms, source="cache" if cache_hit else "decode")

    def _store(self, cache_path: str, img: QImage, w: int = 0, h: int = 0) -> None:
        if w > 0 and h > 0:
            # исходное разрешение сохраняем в самом PNG (tEXt-чанк):
            # попадание в кэш не читает оригинал, а подписи плитки оно нужно
            img.setText(_DIMS_TEXT_KEY, f"{w}x{h}")
        tmp = f"{cache_path}.{os.getpid()}.tmp"
        if not img.save(tmp, "PNG"):
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        try:
            os.replace(tmp, cache_path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return
        if random.random() < 0.02:  # изредка подчищаем кэш в фоновом потоке
            _prune_thumb_cache(self.cache_dir)


class _ViewSignals(QObject):
    ready = Signal(int, str, QImage, str)   # строка, путь, картинка, ошибка


class _ViewTask(QRunnable):
    """Полноразмерный просмотр в фоновом потоке.

    Выбор картинки больше не блокирует интерфейс: чтение и декодирование
    полного файла (тем более по сети — Z:/…, тем более AVIF) идут в фоне,
    окно продолжает отвечать — Windows не пишет «Не отвечает».
    """

    def __init__(self, path: str, row: int, signals: _ViewSignals):
        super().__init__()
        self.path, self.row, self.signals = path, row, signals

    def run(self) -> None:  # рабочий поток
        t0 = time.perf_counter()
        img, err = imgload.load_file(self.path)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= 400:   # медленное чтение/декодирование (сеть, AVIF, огромный файл) — в журнал
            name = os.path.basename(self.path)
            applog.slow_event(tr("perf.op.view_decode", name=name), ms,
                              **({"err": err} if err else {}))
        self.signals.ready.emit(self.row, self.path, img, err)


class _GifSignals(QObject):
    ready = Signal(int, str, bytes, str)   # строка, путь, байты файла, ошибка


class _GifTask(QRunnable):
    """Чтение GIF-файла в рабочий поток (см. _show_index и _on_gif_ready).

    QMovie создаётся по пути файла и читает его в GUI-потоке: на подвисшем
    WebDAV/SMB даже чтение заголовка замораживало окно на весь сетевой
    тайм-аут — тот же класс проблем, что у полноразмерного просмотра
    (v0.7.2). Файл читается питоновским I/O (GIL отпускается), анимация
    строится из памяти поверх QBuffer (v0.7.11).
    """

    def __init__(self, path: str, row: int, signals: _GifSignals):
        super().__init__()
        self.path, self.row, self.signals = path, row, signals

    def run(self) -> None:  # рабочий поток
        t0 = time.perf_counter()
        data, err = imgload.read_file_bytes(self.path)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= 400:   # медленное чтение (сеть) — в журнал
            applog.slow_event(tr("perf.op.view_decode", name=os.path.basename(self.path)),
                              ms, **({"err": err} if err else {}))
        self.signals.ready.emit(self.row, self.path, data or b"", err)


# ---------- фоновое чтение папок и дерева (сеть не заминает интерфейс, v0.7.2) ----------

class _ScanSignals(QObject):
    done = Signal(int, str, list)      # поколение, папка, [(путь, размер, mtime)]


class _ScanTask(QRunnable):
    """Скан папки с картинками в рабочем потоке (см. load_folder).

    os.scandir по сети (WebDAV, SMB) может занять секунды, а на подвисшем
    сервере — сетевой тайм-аут целиком; в GUI-потоке это было бы зависанием
    окна целиком (v0.7.2: открытие папки стало асинхронным)."""

    def __init__(self, folder: str, gen: int, signals: _ScanSignals):
        super().__init__()
        self.folder, self.gen, self.signals = folder, gen, signals

    def run(self) -> None:
        t0 = time.perf_counter()
        entries = scan_image_entries(self.folder)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= 400:   # медленный скан (сеть, проснувшийся диск) — в журнал
            applog.slow_event(tr("perf.op.scan_folder"), ms, files=len(entries))
        self.signals.done.emit(self.gen, self.folder, entries)


class _SubdirsSignals(QObject):
    ready = Signal(int, object, str, list)   # жетон, узел дерева, папка, подпапки


class _SubdirsTask(QRunnable):
    """Чтение подпапок узла дерева в рабочем потоке (см. _populate_children)."""

    def __init__(self, path: str, token: int, item, signals: _SubdirsSignals):
        super().__init__()
        self.path, self.token, self.item = path, token, item
        self.signals = signals

    def run(self) -> None:
        t0 = time.perf_counter()
        subs = LocalViewer._list_subdirs(self.path)
        ms = round((time.perf_counter() - t0) * 1000)
        if ms >= 400:   # медленное чтение папки (сеть) — в журнал
            applog.slow_event(
                tr("perf.op.populate_children",
                   folder=os.path.basename(self.path) or self.path),
                ms, dirs=len(subs))
        self.signals.ready.emit(self.token, self.item, self.path, subs)


class _DrivesSignals(QObject):
    ready = Signal(list)   # [(путь, подпись, объём, свободно), ...] — диски (v0.7.14)


class _DrivesTask(QRunnable):
    """Перечислить смонтированные тома вне GUI-потока (v0.7.14).

    QStorageInfo на сетевом диске платит сетевым тайм-аутом прямо в
    GUI-потоке: при холодном старте первый запрос к ещё не подключённому
    сетевому диску (Z:) устанавливал SMB-сессию, и интерфейс замирал на
    ~2 секунды (репорт: «Интерфейс не отвечал ≈1742 мс» при старте).
    Диски читает рабочий поток; подпись и статистика объёма — там же,
    так что на сетевом диске дерево ждёт ответа, а интерфейс — нет.
    """

    def __init__(self, signals: _DrivesSignals, include_all: bool = False):
        super().__init__()
        self.signals = signals
        self.include_all = include_all

    def run(self) -> None:  # рабочий поток
        out: list[tuple[str, str, int, int]] = []
        for si in QStorageInfo.mountedVolumes():
            if not si.isValid() or not si.isReady():
                continue
            if not self.include_all and _is_virtual_volume(si):
                continue
            path = si.rootPath()
            label = si.displayName() or path
            if os.name != "nt" and label == path:
                label = "💾 " + (path if len(path) > 1 else tr("viewer.drive_root"))
            out.append((path, label, si.bytesTotal(), si.bytesFree()))
        self.signals.ready.emit(out)


class _DeleteSignals(QObject):
    done = Signal(int, list)   # фаза (1 — корзина, 2 — окончательно), [(путь, ok, ошибка)]


class _DeleteTask(QRunnable):
    """Удаление файлов в рабочем потоке (см. delete_selected_files).

    По сети moveToTrash/remove может подвиснуть на сетевой тайм-аут —
    в GUI-потоке это было бы зависанием окна с диалогом «Не отвечает».
    """

    def __init__(self, paths: list[str], perm: bool, phase: int,
                 signals: _DeleteSignals):
        super().__init__()
        self.paths, self.perm, self.phase = paths, perm, phase
        self.signals = signals

    def run(self) -> None:
        results: list[tuple[str, bool, str]] = []
        for p in self.paths:
            if self.perm:
                ok, err = _remove_forever(p)
            else:
                ok, err = _trash_file(p)
            results.append((p, ok, err))
        self.signals.done.emit(self.phase, results)


# ---------- переименование файла (F2, двойной клик по имени, меню; v0.7.17) ----------

def _clean_rename_name(raw: str) -> str:
    """Привести имя от редактора к виду, который согласится с Windows и POSIX.

    Пробелы по краям и точки на конце убираются: Windows такие имена не
    создаёт, а Проводник их молча обрезает. Внутренности не трогаем."""
    return raw.strip().rstrip(". ")


def _name_is_allowed(name: str) -> bool:
    """Имя файла допустимо: непустое и без запрещённых в Windows символов.

    \\ / : * ? \" < > | и управляющие символы — отказ (на POSIX часть из них
    разрешена, но один и тот же список даёт предсказуемое поведение везде)."""
    if not name or name in (".", ".."):
        return False
    return not any(c in name for c in '<>:"/\\|?*') and all(ord(c) >= 32 for c in name)


class _MoveSignals(QObject):
    done = Signal(int, int, int, list, list, str)   # ok, пропущено, ошибки, ошибки[], перенесённые[], папка


def _exclusive_dst(folder: str, name: str) -> str:
    """Свободное имя в folder: если занято — «имя-1.ext», «имя-2.ext»…

    Перемещение в папку дерева ничего не затирает (принцип копирования
    из интернета в websearch.py): файл с тем же именем уже лежит —
    новый получит следующий свободный номер."""
    dst = os.path.join(folder, name)
    if not os.path.lexists(dst):
        return dst
    stem, ext = os.path.splitext(name)
    for i in range(1, 1000):
        cand = os.path.join(folder, f"{stem}-{i}{ext}")
        if not os.path.lexists(cand):
            return cand
    return dst   # не бывает: 999 попыток всегда хватает


class _MoveTask(QRunnable):
    """Перемещение выделенных файлов в папку дерева в рабочем потоке (v0.8.5).

    shutil.move по сети может подвиснуть на сетевой тайм-аут — в GUI-потоке
    это было бы зависанием окна (принцип v0.7.2). Перемещение между дисками
    shutil.move выполняет сам (копирование + удаление). Файлы, уже лежащие
    в целевой папке, пропускаются, а при конфликте имён файл получает
    свободное имя («cat-1.png») — ничего не затирается.
    """

    def __init__(self, paths: list[str], target: str, signals: _MoveSignals):
        super().__init__()
        self.paths, self.target, self.signals = paths, target, signals

    def run(self) -> None:  # рабочий поток
        ok = skip = fail = 0
        moved: list[str] = []          # исходные пути (для чистки ленты)
        errors: list[tuple[str, str]] = []
        target_n = os.path.normcase(os.path.normpath(self.target))
        for src in self.paths:
            if not src:
                continue
            try:
                if (os.path.normcase(os.path.normpath(os.path.dirname(src)))
                        == target_n):
                    skip += 1          # файл уже в этой папке — не трогаем
                    continue
                dst = _exclusive_dst(self.target, os.path.basename(src))
                shutil.move(src, dst)
                moved.append(src)
                ok += 1
            except OSError as e:
                errors.append((os.path.basename(src) or src, str(e)))
                fail += 1
        self.signals.done.emit(ok, skip, fail, errors, moved, self.target)


class _ResizeSignals(QObject):
    # итог сохранения: успех, путь результата, ширина, высота, ошибка
    done = Signal(bool, str, int, int, str)


class _CropSignals(QObject):
    # итог сохранения обрезки: успех, путь результата, ширина, высота, ошибка
    done = Signal(bool, str, int, int, str)


class _ResizeSaveTask(QRunnable):
    """Масштабирование и запись картинки нового размера в рабочем потоке (v0.8.6).

    Масштаб SmoothTransformation на большом фото — десятки-сотни миллисекунд,
    запись на сетевой диск — секунды: GUI не ждёт (принцип v0.7.2). QImage
    можно передавать между потоками (QPixmap — нельзя), поэтому в задачу
    уходит оригинальный QImage, а масштабирование и запись делает рабочий
    поток. Имя «имя_WxH.ext» проверяется на свободу здесь же, непосредственно
    перед записью, — существующие файлы никогда не затираются.
    """

    def __init__(self, img: QImage, w: int, h: int, folder: str, stem: str,
                 ext: str, src_name: str, signals: _ResizeSignals):
        super().__init__()
        self.img, self.w, self.h = img, w, h
        self.folder, self.stem, self.ext = folder, stem, ext
        self.src_name, self.signals = src_name, signals

    def run(self) -> None:  # рабочий поток
        t0 = time.perf_counter()
        try:
            qt_fmt, quality = _resize_format_for(self.ext)
            out = self.img.scaled(self.w, self.h,
                                  Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            if out.isNull():
                raise ValueError("масштабирование не удалось")
            # JPEG и BMP не умеют в прозрачность: альфа → белый фон
            # (те же правила, что при сохранении из интернета, image_saver.py)
            if out.hasAlphaChannel() and qt_fmt in ("JPEG", "BMP"):
                from app.core.image_saver import _flatten_on_white
                out = _flatten_on_white(out)
            name = _free_resize_name(self.folder, self.stem, self.w, self.h,
                                     self.ext)
            path = os.path.join(self.folder, name)
            ok = (out.save(path, qt_fmt) if quality is None
                  else out.save(path, qt_fmt, quality))
            if not ok:
                raise ValueError(f"не удалось записать {qt_fmt}")
            ms = round((time.perf_counter() - t0) * 1000)
            applog.event("log.event.resize", src=self.src_name, dst=name,
                         w=out.width(), h=out.height(),
                         extra=applog.extra(ms=ms))
            self.signals.done.emit(True, path, out.width(), out.height(), "")
        except Exception as exc:  # noqa: BLE001 — текст ошибки уходит в статус
            applog.error(tr("log.event.resize_err",
                            name=self.src_name, err=str(exc)[:200]))
            self.signals.done.emit(False, "", 0, 0, str(exc)[:200])


class _CropSaveTask(QRunnable):
    """Вырезание выделенной области и запись результата в рабочем потоке (v0.8.7).

    QImage.copy на большом фото — десятки миллисекунд, запись на сетевой
    диск — секунды: GUI не ждёт (принцип v0.7.2). Оригинальный QImage не
    режется — копия уходит в файл, оригинал живёт дальше в просмотре.
    Без явного пути свободное имя «имя_crop.ext» проверяется здесь же,
    непосредственно перед записью, — существующие файлы не затираются;
    для «💾 Как…» путь уже выбран человеком в диалоге (Qt спросил
    подтверждение перезаписи) — пишется ровно туда, куда указал человек."""

    def __init__(self, img: QImage, rect: QRect, folder: str, stem: str,
                 ext: str, src_name: str, signals: _CropSignals,
                 dst_path: str = ""):
        super().__init__()
        self.img, self.rect = img, QRect(rect)
        self.folder, self.stem, self.ext = folder, stem, ext
        self.src_name, self.signals = src_name, signals
        self.dst_path = dst_path

    def run(self) -> None:  # рабочий поток
        t0 = time.perf_counter()
        try:
            path = self.dst_path
            if path and not os.path.splitext(path)[1]:
                path = path + self.ext   # «Как…» без расширения — как у оригинала
            if not path:
                path = os.path.join(self.folder,
                                    _free_crop_name(self.folder, self.stem,
                                                    self.ext))
            name = os.path.basename(path)
            out = self.img.copy(self.rect)
            if out.isNull():
                raise ValueError("выделенная область пуста")
            ext2 = os.path.splitext(path)[1].lower()
            # JPEG и BMP не умеют в прозрачность: альфа → белый фон
            # (те же правила, что при сохранении из интернета, image_saver.py)
            if out.hasAlphaChannel() and ext2 in (".jpg", ".jpeg", ".bmp"):
                from app.core.image_saver import _flatten_on_white
                out = _flatten_on_white(out)
            if ext2 in _RESIZE_SAVE_FORMATS:
                qt_fmt, quality = _RESIZE_SAVE_FORMATS[ext2]
                ok = (out.save(path, qt_fmt) if quality is None
                      else out.save(path, qt_fmt, quality))
            else:
                ok = out.save(path)   # незнакомое расширение — Qt разберёт по суффиксу
            if not ok:
                raise ValueError(f"не удалось записать {name}")
            ms = round((time.perf_counter() - t0) * 1000)
            applog.event("log.event.crop", src=self.src_name, dst=name,
                         w=out.width(), h=out.height(),
                         extra=applog.extra(ms=ms))
            self.signals.done.emit(True, path, out.width(), out.height(), "")
        except Exception as exc:  # noqa: BLE001 — текст ошибки уходит в статус
            applog.error(tr("log.event.crop_err",
                            name=self.src_name, err=str(exc)[:200]))
            self.signals.done.emit(False, "", 0, 0, str(exc)[:200])


class _FillSignals(QObject):
    # итог закрашивания: успех, путь результата, ширина, высота, ошибка
    done = Signal(bool, str, int, int, str)


class _FillSaveTask(QRunnable):
    """Запись закрашенной картинки в рабочем потоке (v0.8.8).

    Само закрашивание делается мгновенно в GUI-потоке (QPainter.fillRect —
    микросекунды даже на большом фото), чтобы результат был виден сразу;
    а вот запись GUI не ждёт (принцип v0.7.2): на сетевом диске она может
    занять секунды. Оригинал никогда не меняется — результат отдельный
    файл «имя_fill.ext»; свободное имя проверяется здесь же, непосредственно
    перед записью, — существующие файлы не затираются.
    """

    def __init__(self, img: QImage, folder: str, stem: str, ext: str,
                 src_name: str, signals: _FillSignals):
        super().__init__()
        self.img = img   # уже закрашенная копия: GUI дальше её не трогает
        self.folder, self.stem, self.ext = folder, stem, ext
        self.src_name, self.signals = src_name, signals

    def run(self) -> None:  # рабочий поток
        t0 = time.perf_counter()
        try:
            qt_fmt, quality = _resize_format_for(self.ext)
            name = _free_fill_name(self.folder, self.stem, self.ext)
            path = os.path.join(self.folder, name)
            out = self.img
            # JPEG и BMP не умеют в прозрачность: альфа → белый фон
            # (те же правила, что при сохранении из интернета, image_saver.py)
            if out.hasAlphaChannel() and qt_fmt in ("JPEG", "BMP"):
                from app.core.image_saver import _flatten_on_white
                out = _flatten_on_white(out)
            ok = (out.save(path, qt_fmt) if quality is None
                  else out.save(path, qt_fmt, quality))
            if not ok:
                raise ValueError(f"не удалось записать {name}")
            ms = round((time.perf_counter() - t0) * 1000)
            applog.event("log.event.fill", src=self.src_name, dst=name,
                         w=out.width(), h=out.height(),
                         extra=applog.extra(ms=ms))
            self.signals.done.emit(True, path, out.width(), out.height(), "")
        except Exception as exc:  # noqa: BLE001 — текст ошибки уходит в статус
            applog.error(tr("log.event.fill_err",
                            name=self.src_name, err=str(exc)[:200]))
            self.signals.done.emit(False, "", 0, 0, str(exc)[:200])


class _RenameSignals(QObject):
    done = Signal(str, str, bool, str)   # старый путь, новый путь, ok, ошибка


class _RenameTask(QRunnable):
    """Переименование в рабочем потоке (см. _on_item_changed).

    По сети os.rename может упереться в сетевой тайм-аут — в GUI-потоке это
    было бы зависанием окна (принцип v0.7.2). POSIX-овый os.rename молча
    перезаписал бы существующий файл — на всякий случай проверяем existence:
    переименование «только регистр» на нечувствительной к регистру файловой
    системе (Windows) при этом остаётся разрешённым."""

    def __init__(self, old: str, new: str, signals: _RenameSignals):
        super().__init__()
        self.old, self.new, self.signals = old, new, signals

    def run(self) -> None:  # рабочий поток
        ok, err = True, ""
        try:
            case_only = (os.path.normcase(os.path.abspath(self.new))
                         == os.path.normcase(os.path.abspath(self.old)))
            if os.path.exists(self.new) and not case_only:
                raise FileExistsError(os.path.basename(self.new))
            os.rename(self.old, self.new)
        except OSError as e:
            ok, err = False, str(e)
        self.signals.done.emit(self.old, self.new, ok, err)


# ---------- фоновый поиск по имени ----------

class _SearchSignals(QObject):
    batch = Signal(int, list)            # поколение поиска, порция [(путь, размер, mtime)]
    done = Signal(int, int, bool)        # поколение, всего найдено, усечено ли


class _SearchHandle:
    """Флажок отмены: рабочий поток проверяет, главный — сбрасывает (GIL-атомарно)."""

    __slots__ = ("cancelled",)

    def __init__(self):
        self.cancelled = False


class _SearchTask(QRunnable):
    """Рекурсивный поиск по имени файла от текущей папки вниз, одним os.scandir
    на папку, без лишних stat() (важно для сетевых дисков). Отдаёт результаты
    порциями, не дожидаясь конца обхода.

    ``ignore_dash`` — искать, не различая дефисы: запрос «23542-23523»
    найдёт и «2354223523», и «23542-23523» (артикулы запчастей пишут
    то с дефисом, то без, и не всегда на том же месте)."""

    MAX_RESULTS = 5000    # предел выдачи
    MAX_FOLDERS = 20000   # предел обхода (страховка от гигантских деревьев)
    BATCH = 50

    def __init__(self, base: str, needle: str, gen: int,
                 signals: _SearchSignals, handle: _SearchHandle,
                 ignore_dash: bool = False):
        super().__init__()
        self.base, self.needle = base, needle
        self.gen, self.signals, self.handle = gen, signals, handle
        self.ignore_dash = ignore_dash
        self.needle_plain = needle.replace("-", "") if ignore_dash else needle

    def _match(self, name: str) -> bool:
        """Подстрока в имени; в режиме «игнорировать дефис» — без дефисов с обеих сторон."""
        name_l = name.lower()
        if self.ignore_dash:
            return self.needle_plain in name_l.replace("-", "")
        return self.needle in name_l

    def run(self) -> None:
        t0 = time.perf_counter()
        found: list[tuple[str, int, float]] = []
        pending: list[tuple[str, int, float]] = []
        truncated = False
        folders = 0
        stack = [self.base]
        while stack:
            if self.handle.cancelled:
                return
            if len(found) >= self.MAX_RESULTS or folders >= self.MAX_FOLDERS:
                truncated = True
                break
            d = stack.pop()
            folders += 1
            dirs: list[str] = []
            matches: list[tuple[str, int, float]] = []
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        name = entry.name
                        if name.startswith(".") or _is_hidden_entry(entry):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                dirs.append(entry.path)
                            elif (os.path.splitext(name)[1].lower() in IMAGE_EXTS
                                  and self._match(name)):
                                st = entry.stat(follow_symlinks=False)
                                matches.append((entry.path, st.st_size, st.st_mtime))
                        except OSError:
                            continue
            except OSError:
                continue
            matches.sort(key=lambda t: natural_key(os.path.basename(t[0])))
            found.extend(matches)
            pending.extend(matches)
            dirs.sort(key=lambda p: natural_key(os.path.basename(p)))
            stack.extend(reversed(dirs))   # pop() берёт конец — обход по порядку
            if len(pending) >= self.BATCH:
                self.signals.batch.emit(self.gen, pending)
                pending = []
        if self.handle.cancelled:
            return
        if pending:
            self.signals.batch.emit(self.gen, pending)
        self.signals.done.emit(self.gen, len(found), truncated)
        applog.event("log.event.timing",
                     op=tr("perf.op.search_scan", q=self.needle),
                     ms=round((time.perf_counter() - t0) * 1000),
                     extra=applog.extra(folders=folders, files=len(found),
                                        cut=truncated))


# ---------- фильтр папок в дереве «Диски и папки» ----------

# Сколько ещё не раскрытых папок фильтр догружает за одно применение и сколько
# секунд на это отводится: обычное домашнее дерево покрывается целиком за доли
# секунды, а гигантский или сетевой диск не подвесит окно. Уже раскрытые папки
# не перечитываются, поэтому каждая следующая буква почти ничего не стоит.
_FS_DIR_BUDGET = 300
_FS_TIME_BUDGET = 1.5


# ---------- виджет ----------

def make_file_urls_mime(paths: list[str]) -> QMimeData:
    """MIME с выбранными файлами (text/uri-list) — то, что понимают Проводник,
    почтовый клиент и другие приложения: передаются пути-оригиналы."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


def _drag_action_name(action) -> str:
    """Человеческое название того, чем закончилось перетаскивание."""
    if action == Qt.DropAction.CopyAction:
        return tr("log.act.copy")
    if action == Qt.DropAction.MoveAction:
        return tr("log.act.move")
    return tr("log.act.cancel")


class _NameEdit(QLineEdit):
    """Поле редактирования имени (открывается двойным кликом по имени плитки,
    F2 или меню). При получении фокуса выделяет имя БЕЗ расширения — как
    Проводник: правят обычно имя, а не формат.

    Особенность Qt: QAbstractItemView::openEditor делает editor->selectAll()
    ПОСЛЕ delegate->setEditorData, поэтому выделение, выставленное прямо в
    setEditorData, затирается. Выделяем отложенным одиночным тиком (таймер с
    контекстом редактора: редактор уже закрыт — вызов не случится) и
    повторяем при каждом возврате фокуса в поле.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_pending = False

    def arm_base_selection(self) -> None:
        self._base_pending = True
        QTimer.singleShot(0, self, self._apply_base_selection)

    def focusInEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        super().focusInEvent(ev)
        if self.text():
            QTimer.singleShot(0, self, self._apply_base_selection)

    def _apply_base_selection(self) -> None:
        if not self._base_pending or not self.text():
            return
        self._base_pending = False
        base, dot, _ext = self.text().rpartition(".")
        if dot and base:
            self.setSelection(0, len(base))
        else:
            self.selectAll()   # «.gitignore» и «кот» правят целиком


class _RenameDelegate(QStyledItemDelegate):
    """Делегат ленты: редактор имени — _NameEdit (имя без расширения)."""

    def createEditor(self, parent, option, index):  # noqa: N802 (Qt API)
        return _NameEdit(parent)

    def setEditorData(self, editor, index):  # noqa: N802 (Qt API)
        super().setEditorData(editor, index)
        if isinstance(editor, _NameEdit):
            editor.arm_base_selection()


class _ThumbDelegate(_RenameDelegate):
    """Плитка ленты: подпись в две строки — имя файла и разрешение (v0.8.4).

    Разрешение узнаётся позже имени (вместе с миниатюрой, из фонового
    потока) и живёт в отдельной роли плитки (_RES_ROLE): сам текст плитки
    остаётся чистым именем файла — на него завязаны переименование, поиск
    и восстановление после удаления. Высота плитки всегда с запасом под
    вторую строку, чтобы лента не «прыгала», когда разрешение доезжает.

    Рисуется всё вручную: QStyledItemDelegate::paint заново читает
    DisplayRole из модели и затёр бы пустой текст, которым мы гасим
    стандартную однострочную подпись. Фон/выделение/фокус и прямоугольники
    иконки и подписи берутся у стиля — раскладка совпадает со штатной."""

    def _style_rect(self, view, index, element) -> QRect:
        """Прямоугольник элемента плитки от стиля — та же механика, что в paint().

        Свежая опция пуста: initStyleOption заполняет только данные плитки
        (текст, иконку, шрифт), а РАСКЛАДОЧНЫЕ поля (rect, размер и позиция
        миниатюры, шрифт вьюхи) ставит сама вьюха перед paint(). Повторяем
        её действия — иначе стиль посчитает прямоугольники по умолчаниям
        и соврёт. Стиль раскладку знает лучше любой формулы: отступы между
        миниатюрой и подписью у стилей Windows свои, у Fusion — свои, и
        хит-тест двойного клика обязан следовать тому, что делегат реально
        рисует, а не константе (v0.8.16)."""
        opt = QStyleOptionViewItem()
        self.initStyleOption(opt, index)
        opt.rect = view.visualRect(index)
        opt.widget = view.viewport()
        opt.font = view.font()
        opt.fontMetrics = view.fontMetrics()
        opt.decorationSize = view.iconSize()
        opt.decorationPosition = QStyleOptionViewItem.Position.Top
        opt.decorationAlignment = (Qt.AlignmentFlag.AlignHCenter
                                   | Qt.AlignmentFlag.AlignTop)
        return view.style().subElementRect(element, opt, view.viewport())

    def icon_rect(self, view, index) -> QRect:
        """Прямоугольник миниатюры, который paint() рисует в этой плитке."""
        return self._style_rect(
            view, index, QStyle.SubElement.SE_ItemViewItemDecoration)

    def caption_rect(self, view, index) -> QRect:
        """Прямоугольник подписи (имя и разрешение), который рисует paint()."""
        return self._style_rect(
            view, index, QStyle.SubElement.SE_ItemViewItemText)

    def sizeHint(self, option, index):  # noqa: N802 (Qt API)
        sz = super().sizeHint(option, index)
        extra = option.fontMetrics.height()
        return QSize(sz.width(), sz.height() + extra)

    def paint(self, painter, option, index) -> None:  # noqa: N802 (Qt API)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name = opt.text
        res = str(index.data(_RES_ROLE) or "")
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()

        # фон, выделение, фокус — как у обычной плитки
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, widget)
        if opt.state & QStyle.StateFlag.State_HasFocus:
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_FrameFocusRect, opt, painter, widget)

        # миниатюра — в ровно том же прямоугольнике, что у штатного делегата
        if not opt.icon.isNull():
            icon_rect = style.subElementRect(
                QStyle.SubElement.SE_ItemViewItemDecoration, opt, widget)
            if not icon_rect.isEmpty():
                opt.icon.paint(painter, icon_rect)

        # подпись: имя, под ним разрешение — меньшим серым шрифтом
        rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        painter.save()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.setFont(opt.font)
        painter.setPen(opt.palette.color(
            QPalette.ColorRole.HighlightedText if selected
            else QPalette.ColorRole.Text))
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(QRect(rect.x(), rect.y(), rect.width(), fm.height()),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         elided)
        if res and rect.height() >= 2 * fm.height():
            f = QFont(opt.font)
            if opt.font.pointSizeF() > 0:
                f.setPointSizeF(max(7.0, opt.font.pointSizeF() - 1.0))
            elif opt.font.pixelSize() > 0:
                f.setPixelSize(max(9, opt.font.pixelSize() - 1))
            fm2 = QFontMetrics(f)
            painter.setFont(f)
            painter.setPen(opt.palette.color(
                QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                QRect(rect.x(), rect.y() + fm.height(), rect.width(), fm2.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                res)
        painter.restore()


class _ThumbList(QListWidget):
    """Список миниатюр: перетаскивание выделенных файлов мышью в другие приложения.

    Зажали кнопку на плитке и потянули — полетели все выделенные файлы
    (Ctrl и Shift выделяют, как в Проводнике). Запуск драга подстрахован
    тремя независимыми путями — хотя бы один да сработает:

      1. eventFilter на viewport — самый ранний перехват движения мыши;
      2. собственные mousePressEvent/mouseMoveEvent с порогом в 12 px;
      3. встроенная механика QListWidget (dragEnabled → startDrag).

    Если событие нажатия до нас не доехало (перехвачено чужим обработчиком,
    потеряно при передаче между виджетами), первый же перенос мыши с зажатой
    кнопкой восстанавливает точку нажатия — и перетаскивание всё равно
    начнётся. Каждый шаг пишется в «Журнал»: по нему видно, начался ли драг
    и почему нет. Если перетаскивание не срабатывает совсем — есть путь
    без драга: Ctrl+C (или правый клик → «Копировать выделенные файлы»),
    затем вставить файлы куда нужно (Ctrl+V).
    """

    DRAG_THRESHOLD = 12        # px манхэттенского смещения, после которого тянем
    DRAG_FACTORY = QDrag       # для подмены в тестах

    nameDoubleClicked = Signal(object)   # плитка, у которой кликнули по ИМЕНИ

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_index = None     # плитка, на которой зажали мышь
        self._press_pos = None       # точка нажатия в координатах виджета
        self._press_max = 0          # наибольшее смещение с момента нажатия, px
        self._press_skip = ""        # почему в этом нажатии драг не начинался
        self._dragging = False
        # слой 1: события viewport ловим до того, как их раздаст QListWidget
        self.viewport().installEventFilter(self)

    def selected_paths(self) -> list[str]:
        """Пути файлов, лежащие в выделенных плитках."""
        return [it.data(Qt.UserRole) for it in self.selectedItems()
                if it.data(Qt.UserRole)]

    # ---------- двойной клик: по имени — переименовать (v0.7.17, зона — v0.8.16) ----------

    def _name_rect(self, item) -> QRect:
        """Зона переименования: всё, что ПОД миниатюрой плитки (v0.8.16).

        Двойной клик по подписи — переименовать, по самой картинке —
        открыть. Границу считает стиль: делегат отдаёт прямоугольник
        миниатюры, который сам же и рисует (initStyleOption +
        SE_ItemViewItemDecoration — ровно механика paint()), и зона имени
        идёт от нижнего края миниатюры до низа плитки. Так хит-тест
        следует нарисованному при любой раскладке: раньше граница была
        константой iconSize+2, у стилей Windows подпись начинается не там,
        и клик по видимому имени улетал мимо зоны — вместо редактора
        открывался файл. Зазор между миниатюрой и подписью тоже зона
        имени: промахнуться труднее, а клик по картинке по-прежнему
        открывает файл. Стиль не отдал прямоугольник — прежняя формула
        от размера иконки."""
        r = self.visualItemRect(item)
        deco = QRect()
        d = self.itemDelegate()
        if hasattr(d, "icon_rect"):
            deco = d.icon_rect(self, self.indexFromItem(item))
        if deco.isValid() and not deco.isEmpty() and deco.bottom() < r.bottom() - 1:
            top = deco.bottom() + 1
        else:
            top = r.top() + self.iconSize().height() + 2   # прежняя граница
        return QRect(r.x(), top, r.width(), max(1, r.bottom() - top + 1))

    def _pos_on_name(self, item, pos: QPoint) -> bool:
        """Клик пришёлся на подпись плитки (имя файла), а не на картинку."""
        r = self.visualItemRect(item)
        return r.contains(pos) and pos.y() >= self._name_rect(item).top()

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(ev.position().toPoint())
            if (item is not None and item.data(Qt.UserRole)
                    and self._pos_on_name(item, ev.position().toPoint())):
                # двойной клик по имени — переименовать; super() НЕ зовём:
                # он эмитит itemDoubleClicked, который открывает файл
                self.nameDoubleClicked.emit(item)
                ev.accept()
                return
        super().mouseDoubleClickEvent(ev)   # по картинке — открыть как раньше

    # ---------- запуск перетаскивания (общий для всех трёх слоёв) ----------

    def startDrag(self, actions) -> None:  # noqa: N802 (Qt API)
        if self._dragging:
            return   # в этом нажатии уже потащили — второй раз не стартуем
        self.exec_drag()

    def exec_drag(self) -> bool:
        """Собрать выделенные файлы и запустить перетаскивание.

        Возвращает True, если перетаскивание действительно началось."""
        paths = self.selected_paths()
        if not paths:
            return False
        drag = self.DRAG_FACTORY(self)
        mime = make_file_urls_mime(paths)
        # запасной формат для программ, которые не понимают uri-list
        mime.setText("\n".join(paths))
        drag.setMimeData(mime)
        # за курсором едет миниатюра первого выбранного файла
        items = self.selectedItems()
        if items:
            pix = items[0].icon().pixmap(THUMB, THUMB)
            if not pix.isNull():
                drag.setPixmap(pix.scaled(96, 96, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
        self._dragging = True
        applog.event("log.event.drag_start", n=len(paths),
                     names=", ".join(os.path.basename(p) for p in paths[:3]))
        action = drag.exec(Qt.CopyAction, Qt.CopyAction)
        applog.event("log.event.drag_end", action=_drag_action_name(action))
        return True

    # ---------- слой 2: собственный запуск по нажатию и движению мыши ----------

    def _remember_press(self, pos: QPoint) -> None:
        """Запомнить плитку и точку нажатия — от них отсчитывается порог."""
        idx = self.indexAt(pos)
        self._press_index = idx if idx.isValid() else None
        self._press_pos = pos
        self._press_max = 0
        self._press_skip = ""

    def _track_distance(self, pos: QPoint) -> None:
        dist = (pos - self._press_pos).manhattanLength()
        if dist > self._press_max:
            self._press_max = dist

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        self._dragging = False
        if ev.button() == Qt.MouseButton.LeftButton:
            self._remember_press(ev.position().toPoint())
        super().mousePressEvent(ev)   # выделение работает как раньше

    def _try_start_drag(self) -> bool:
        """Порог пройден и плитка выделена — начать перетаскивание."""
        item = self.itemFromIndex(self._press_index)
        if item is None or not item.isSelected():
            # причину запоминаем именно сейчас: встроенная механика Qt при
            # движении может перевыбрать плитку, и к отпусканию кнопки
            # isSelected() уже не скажет, почему драг не начался
            self._press_skip = tr("log.why.not_selected")
            return False
        started = self.exec_drag()      # блокирует до отпускания кнопки
        self._press_index = None
        return started

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if (self._press_index is not None and not self._dragging
                and ev.buttons() & Qt.MouseButton.LeftButton
                and self._press_pos is not None):
            self._track_distance(ev.position().toPoint())
            if self._press_max > self.DRAG_THRESHOLD:
                if self._try_start_drag():
                    ev.accept()
                    return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        # диагностика для «Журнала»: плитку зажали и ощутимо повели,
        # а перетаскивание так и не началось — объясняем почему
        if (self._press_index is not None and not self._dragging
                and self._press_max > self.DRAG_THRESHOLD
                and ev.button() == Qt.MouseButton.LeftButton
                and self._press_skip):
            applog.event("log.event.drag_no", why=self._press_skip)
        self._press_index = None
        self._press_pos = None
        self._press_max = 0
        self._press_skip = ""
        self._dragging = False   # жест окончен — при следующем нажатии можно тащить
        super().mouseReleaseEvent(ev)

    # ---------- слой 1: самый ранний перехват событий viewport ----------

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 (Qt API)
        if obj is self.viewport() and not self._dragging:
            ev_type = ev.type()
            if (ev_type == QEvent.Type.MouseButtonPress
                    and ev.button() == Qt.MouseButton.LeftButton):
                self._remember_press(ev.position().toPoint())
            elif (ev_type == QEvent.Type.MouseMove
                    and ev.buttons() & Qt.MouseButton.LeftButton):
                if self._press_pos is None:
                    # нажатие не дошло до нас (потерялось по пути) —
                    # восстанавливаем точку нажатия по текущему положению мыши
                    self._remember_press(ev.position().toPoint())
                elif self._press_index is not None:
                    self._track_distance(ev.position().toPoint())
                    if self._press_max > self.DRAG_THRESHOLD:
                        if self._try_start_drag():
                            ev.accept()
                            return True      # драг начался — движение обработано
        return super().eventFilter(obj, ev)


class _GripEdit(QLineEdit):
    """Однострочное поле, ширину которого меняют мышью за левый или правый край.

    У краёв (6 px) курсор превращается в «↔»; зажали мышь у края — тянете,
    ширина меняется на ходу и запоминается в QSettings. В середине поле
    работает как обычный QLineEdit: ввод, выделение, двойной клик.
    """

    EDGE = 6        # ширина зоны захвата у края, px
    MIN_W = 170     # уже не сузить (чтобы поле не потерялось на панели)
    MAX_W = 640     # шире не растянуть (иначе вытеснит соседние кнопки)

    def __init__(self, settings_key: str, default_w: int = 220, parent=None):
        super().__init__(parent)
        self._key = settings_key
        self._default_w = default_w
        self._grip = ""          # "l" | "r" | "" — тянем ли сейчас за край
        self._press_x = 0        # глобальный X в момент захвата
        self._start_w = 0        # ширина в момент захвата
        self.setMouseTracking(True)   # движение без кнопки — для курсора-захвата
        saved = QSettings("ImageHunter", "ImageHunter").value(
            settings_key, default_w, int)
        try:
            saved = int(saved)
        except (TypeError, ValueError):
            saved = default_w
        self.setFixedWidth(max(self.MIN_W, min(self.MAX_W, saved)))

    def _edge_at(self, pos) -> str:
        """Зона захвата под курсором: «l», «r» или пусто — середина."""
        if pos.x() <= self.EDGE:
            return "l"
        if pos.x() >= self.width() - self.EDGE:
            return "r"
        return ""

    def mousePressEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if ev.button() == Qt.MouseButton.LeftButton:
            edge = self._edge_at(ev.position().toPoint())
            if edge:
                self._grip = edge
                self._press_x = int(ev.globalPosition().x())
                self._start_w = self.width()
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._grip:
            dx = int(ev.globalPosition().x()) - self._press_x
            delta = dx if self._grip == "r" else -dx
            new_w = max(self.MIN_W, min(self.MAX_W, self._start_w + delta))
            if new_w != self.width():
                self.setFixedWidth(new_w)
            ev.accept()
            return
        # просто наведение: подсказываем захват у краёв
        edge = self._edge_at(ev.position().toPoint())
        self.setCursor(Qt.CursorShape.SizeHorCursor if edge
                       else Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._grip:
            self._grip = ""
            QSettings("ImageHunter", "ImageHunter").setValue(
                self._key, self.width())
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._edge_at(ev.position().toPoint()):
            ev.accept()   # у края двойной клик — это захват, а не выделение слова
            return
        super().mouseDoubleClickEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if not self._grip:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        super().leaveEvent(ev)


_REMBG_SAVE = 1     # код завершения диалога выбора: сохранить результат
_REMBG_REVERT = 2   # …вернуть оригиналы (Esc/крестик дают 0 = «сохранить»)


class _RembgChoiceDialog(QDialog):
    """Выбор после модуля: сохранить результат или вернуть оригиналы.

    Немодальный: пока окно открыто, лента живёт — можно щёлкать по плиткам
    «*_nobg.png» и смотреть результаты в полном размере, решать не
    вслепую. Превью первого результата рисуется на «шахматке», чтобы
    прозрачность была видна сразу. Esc и крестик закрывают окно как
    «Сохранить» — результат теряется только по явному клику.

    Тексты параметризуются (v0.8.24): диалог делит модуль улучшения
    качества — по умолчанию остаются ключи удаления фона, чтобы прежние
    вызовы не менялись."""

    def __init__(self, parent, results: list[str],
                 preview: QPixmap | None,
                 title_key: str = "viewer.rembg",
                 q_key: str = "viewer.rembg_choice_q",
                 more_key: str = "viewer.rembg_choice_more",
                 revert_key: str = "viewer.rembg_btn_revert",
                 revert_tip_key: str = "viewer.rembg_btn_revert_tip",
                 save_key: str = "viewer.rembg_btn_save",
                 save_tip_key: str = "viewer.rembg_btn_save_tip") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(title_key))
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        info = QLabel(tr(q_key, n=len(results)))
        info.setWordWrap(True)
        lay.addWidget(info)
        if preview is not None:
            pic = QLabel()
            pic.setPixmap(preview)
            pic.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(pic)
            cap = os.path.basename(results[0])
            if len(results) > 1:
                cap += " " + tr(more_key, n=len(results) - 1)
            cap_lbl = QLabel(cap)
            cap_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(cap_lbl)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_revert = QPushButton(tr(revert_key))
        self.btn_revert.setToolTip(tr(revert_tip_key))
        self.btn_revert.clicked.connect(lambda: self.done(_REMBG_REVERT))
        row.addWidget(self.btn_revert)
        self.btn_save = QPushButton(tr(save_key))
        self.btn_save.setToolTip(tr(save_tip_key))
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)   # accept() = «сохранить»
        row.addWidget(self.btn_save)
        lay.addLayout(row)


class _Tree(QTreeWidget):
    """Дерево дисков/папок, принимающее перетаскиваемые файлы (v0.8.5).

    Выделенные файлы из ленты миниатюр (или из Проводника) бросаются на
    узел дерева — папку или диск — и переносятся туда. Рисуем indicator
    подсветкой узла под курсором: точный QStyle-индикатор QTreeWidget
    при DragOnly-режиме рисовать отказывается (декодирует только свои
    mime-модели), а подсветка папки виднее и надёжнее.

    Папка, над которой держат файл, сама раскрывается через паузу — как
    в Проводнике: глубоко лежащую цель не надо предварительно искать.
    Раскрытие штатное (itemExpanded → _populate_children), догрузка
    подпапок идёт фоном и интерфейс не замирает (v0.7.2).
    """

    HOVER_EXPAND_MS = 800     # сколько держать файл над папкой до раскрытия

    def __init__(self, viewer: "LocalViewer"):
        super().__init__()
        self.viewer = viewer
        self._hover_item: QTreeWidgetItem | None = None
        self._hover_t0: QElapsedTimer | None = None
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setToolTip(tr("viewer.tree_drop_tip"))

    # ---------- цель перетаскивания ----------

    def _drop_target(self, pos: QPoint) -> QTreeWidgetItem | None:
        """Узел-папка (или диск) под точкой pos — или None, если цели нет."""
        item = self.itemAt(pos)
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole):
            return item
        return None

    def _paths_from_mime(self, mime) -> list[str]:
        """Локальные пути из mime (text/uri-list). Существование файлов
        и конфликты проверяет _MoveTask в рабочем потоке: stat по сети
        в GUI-потоке может подвиснуть интерфейс (v0.7.2)."""
        if mime is None or not mime.hasUrls():
            return []
        out = []
        for u in mime.urls():
            if u.isLocalFile() and u.toLocalFile():
                out.append(u.toLocalFile())
        return out

    # ---------- подсветка узла под курсором ----------

    def _set_hover(self, item: QTreeWidgetItem | None) -> None:
        """Подсветить узел-цель (полупрозрачным цветом выделения), прежний
        узел вернуть как был. Узлы дерева перестраиваются на лету —
        мёртвые ссылки проверяем shiboken'ом, как _on_subdirs_ready."""
        old, self._hover_item = self._hover_item, item
        if old is not None:
            try:
                if shiboken6.isValid(old):
                    old.setBackground(0, QBrush())
            except RuntimeError:
                pass
        if item is not None:
            c = QColor(self.palette().color(QPalette.ColorRole.Highlight))
            c.setAlpha(70)
            item.setBackground(0, QBrush(c))
            self.scrollToItem(item)
            self._hover_t0 = QElapsedTimer()
            self._hover_t0.start()
        else:
            self._hover_t0 = None

    def _auto_expand_hover(self) -> None:
        """Файл держат над свёрнутой папке HOVER_EXPAND_MS — раскрыть её."""
        if (self._hover_item is not None and self._hover_t0 is not None
                and not self._hover_item.isExpanded()):
            if self._hover_t0.elapsed() >= self.HOVER_EXPAND_MS:
                self._hover_item.setExpanded(True)   # → _populate_children

    # ---------- события перетаскивания ----------

    def dragEnterEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        if self._paths_from_mime(ev.mimeData()) and self._drop_target(ev.position().toPoint()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        item = self._drop_target(ev.position().toPoint())
        if not self._paths_from_mime(ev.mimeData()) or item is None:
            self._set_hover(None)
            ev.ignore()
            return
        if item is not self._hover_item:
            self._set_hover(item)
        self._auto_expand_hover()
        ev.acceptProposedAction()

    def dragLeaveEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        self._set_hover(None)
        ev.accept()

    def dropEvent(self, ev) -> None:  # noqa: N802 (Qt API)
        item = self._drop_target(ev.position().toPoint())
        paths = self._paths_from_mime(ev.mimeData())
        self._set_hover(None)
        if item is None or not paths:
            ev.ignore()
            return
        target = item.data(0, Qt.ItemDataRole.UserRole)
        ev.acceptProposedAction()
        ev.setDropAction(Qt.DropAction.CopyAction)   # QDrag вернёт не «отмена»
        self.viewer.move_files_to(paths, target)


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
        self._gen = 0                      # номер загрузки папки: отсекаем миниатюры прошлой папки
        self._pending_thumbs: dict[int, QImage] = {}
        self._search_handle = None         # отменяемый текущий поиск
        self._search_needle = ""
        self._search_count = 0
        self._meta: list[tuple[int, float]] = []   # (размер, mtime) параллельно _paths
        self._thumb_queued: set[int] = set()       # строки, для которых задача уже ставилась
        self._thumb_done_rows: set[int] = set()    # строки с уже выставленной миниатюрой
        self._thumbs_enabled = QSettings("ImageHunter", "ImageHunter").value(
            "viewer/thumbs", True, type=bool)      # выключатель предпросмотра
        self._fs_applying = False        # фильтр папок применяется прямо сейчас (от повторного входа)
        # фон-«шахматка» под прозрачными картинками (v0.7.16): включается
        # только для картинок с альфа-каналом, размер клетки — ползунком
        self._checker_on = False
        self._checker_cell = _checker_cell_setting()
        # переименование файла (v0.7.17): не больше одной задачи за раз —
        # пока она едет, редактор имени не открывается заново
        self._rename_inflight = False
        self._rename_signals = _RenameSignals()
        self._rename_signals.done.connect(self._on_rename_done)
        # разрешение картинок для подписи плиток: приходит вместе с миниатюрой
        # (v0.8.4), ключ — номер строки, значение — готовая строка «Ш×В»
        self._pending_dims: dict[int, str] = {}
        # изменение размера картинки мышью (v0.8.6): целевой размер показанной
        # картинки (QSize) или None вне режима; сохранение — не чаще одной
        # фоновой задачи за раз, как у переименования
        self._resize_mode = False
        self._resize_size: QSize | None = None
        self._resize_orig: QSize | None = None
        self._resize_handle = 0
        self._resize_start: QSize | None = None
        self._resize_saving = False
        self._resize_signals = _ResizeSignals()
        self._resize_signals.done.connect(self._on_resize_save_done)
        # путь, который надо открыть после пересканирования ленты (v0.8.6):
        # после сохранения уменьшенной копии лента обновится и покажет её
        self._select_after_scan = ""
        # обрезка картинки мышью, как в XnView (v0.8.7): выделение хранит сам
        # вью (в координатах картинки — переживает смену зума), вьюеру
        # остаётся статус, кнопки и запись; сохранение — не чаще одной
        # фоновой задачи за раз; «✂▶ К следующему» продолжает серию
        self._crop_mode = False
        self._crop_saving = False
        self._crop_continue = False
        self._crop_next_row = -1
        self._crop_signals = _CropSignals()
        self._crop_signals.done.connect(self._on_crop_save_done)
        # пипетка (v0.8.8): взятый цвет живёт, пока открыта вкладка (его
        # использует «🪣 Закрасить»), источник чтения — только в режиме
        # пипетки; правый клик берёт цвет и без режима (картинка читается
        # на лету); подсказка «цвет в буфере» не гасится наведением
        self._picker_mode = False
        self._picker_color: QColor | None = None
        self._picker_img: QImage | None = None
        self._picker_hold = 0.0
        # закрашивание выделенной области (v0.8.8): не чаще одной фоновой
        # задачи за раз; на время записи показ можно откатить к оригиналу
        self._fill_saving = False
        self._fill_prev_pixmap: QPixmap | None = None
        self._fill_signals = _FillSignals()
        self._fill_signals.done.connect(self._on_fill_save_done)

        # --- верхняя панель ---
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)

        # (кнопка, ключ_текста | None, ключ_подсказки) — для перетрансляции при смене языка
        self._i18n_buttons: list[tuple[QToolButton, str | None, str]] = []

        def btn(text_key: str | None, tip_key: str, slot, shortcut=None,
                literal: str | None = None,
                lay: QHBoxLayout | None = None) -> QToolButton:
            b = QToolButton()
            if text_key is not None:
                b.setText(tr(text_key))
            elif literal is not None:
                b.setText(literal)
            b.setToolTip(tr(tip_key))
            b.clicked.connect(slot)
            if shortcut:
                sc = QShortcut(QKeySequence(shortcut), self)
                sc.activated.connect(slot)
            (lay or bar).addWidget(b)
            self._i18n_buttons.append((b, text_key, tip_key))
            return b

        btn("viewer.open_folder", "viewer.open_folder_tip", self.open_folder, "Ctrl+O")
        bar.addSpacing(8)
        self.btn_thumbs = QToolButton()
        self.btn_thumbs.setText(tr("viewer.thumbs"))
        self.btn_thumbs.setCheckable(True)
        self.btn_thumbs.setChecked(self._thumbs_enabled)
        self.btn_thumbs.setToolTip(tr("viewer.thumbs_tip"))
        self.btn_thumbs.toggled.connect(self._on_toggle_thumbs)
        bar.addWidget(self.btn_thumbs)
        self._i18n_buttons.append((self.btn_thumbs, "viewer.thumbs", "viewer.thumbs_tip"))
        bar.addSpacing(8)
        self.btn_prev = btn(None, "viewer.prev_tip", lambda: self.step(-1), literal="◀")
        self.btn_next = btn(None, "viewer.next_tip", lambda: self.step(+1), literal="▶")
        bar.addSpacing(8)
        btn(None, "viewer.zoom_out_tip", lambda: self.zoom(1 / 1.25), literal="−")
        btn(None, "viewer.actual_tip", lambda: self.set_manual_zoom(1.0), literal="100%")
        btn(None, "viewer.fit_tip", self.fit_to_window, literal="◱")
        btn(None, "viewer.zoom_in_tip", lambda: self.zoom(1.25), literal="+")
        bar.addSpacing(8)
        # фон-«шахматка» под прозрачными картинками: размер клетки — ползунком
        # (v0.7.16). Иконка-шахматка подсказывает, что регулирует ползунок.
        self.checker_icon = QLabel()
        self.checker_icon.setPixmap(_mini_checker_icon())
        self.checker_icon.setToolTip(tr("viewer.checker_tip"))
        bar.addWidget(self.checker_icon)
        self.checker_slider = QSlider(Qt.Orientation.Horizontal)
        self.checker_slider.setRange(CHECKER_MIN, CHECKER_MAX)
        self.checker_slider.setValue(self._checker_cell)
        self.checker_slider.setFixedWidth(92)
        self.checker_slider.setToolTip(tr("viewer.checker_tip"))
        self.checker_slider.valueChanged.connect(self._on_checker_cell)
        bar.addWidget(self.checker_slider)
        bar.addSpacing(8)
        btn("viewer.reveal", "viewer.reveal_tip", self.reveal_folder)
        bar.addSpacing(8)
        self.search_edit = _GripEdit("viewer/search_width", default_w=220)
        self.search_edit.setPlaceholderText(tr("viewer.search_ph"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(tr("viewer.search_tip"))
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._start_search_now)
        bar.addWidget(self.search_edit)
        # «игнорировать дефис»: артикулы пишут то с дефисом, то без — ищем без различий
        self.ignore_dash_box = QCheckBox(tr("viewer.ignore_dash"))
        self.ignore_dash_box.setToolTip(tr("viewer.ignore_dash_tip"))
        self.ignore_dash_box.setChecked(QSettings("ImageHunter", "ImageHunter").value(
            "viewer/search_ignore_dash", False, type=bool))
        self.ignore_dash_box.toggled.connect(self._on_ignore_dash_toggled)
        bar.addWidget(self.ignore_dash_box)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.activated.connect(self._escape_search)   # Esc чистит то поле, где фокус
        bar.addStretch(1)
        # статус поиска/операций («Поиск «…»: N файлов» и т.п.) показывается
        # не здесь, а внизу окна — в строке статуса главного окна рядом с
        # языком (v0.7.7). Метка создаётся без родителя: главное окно добавит
        # её к статус-бару через addPermanentWidget.
        self.status = QLabel(tr("viewer.pick"))
        self.status.setStyleSheet("color: #666;")

        # --- панель инструментов картинки (v0.8.9) ---
        # «⇲ Размер», «✂ Обрезать», «💧 Пипетка» и все сопутствующие элементы
        # переехали из верхней панели на ОТДЕЛЬНУЮ ПАНЕЛЬ ПОД НЕЙ (пожелание:
        # «изменение размера, обрезания, пипетку и все сопутствующие элементы
        # перенеси на новую панель ниже»): верхняя панель осталась про
        # навигацию — папки, лента, зум, поиск; редактирование живёт своей
        # строкой и заметно сразу.
        self.tools_panel = QFrame()
        self.tools_panel.setObjectName("toolsPanel")
        self.tools_panel.setStyleSheet(
            "QFrame#toolsPanel { background: rgba(21, 101, 216, 0.05);"
            " border-top: 1px solid #d6dce6; border-bottom: 1px solid #d6dce6; }")
        tools_lay = QHBoxLayout(self.tools_panel)
        tools_lay.setContentsMargins(8, 4, 6, 5)
        tools_lay.setSpacing(4)

        # подсказка-разделитель между группами инструментов
        def vline() -> QFrame:
            ln = QFrame()
            ln.setFrameShape(QFrame.Shape.VLine)
            ln.setFrameShadow(QFrame.Shadow.Sunken)
            return ln

        self.tools_title = QLabel(tr("viewer.tools_title"))
        self.tools_title.setStyleSheet("color: #666;")
        tools_lay.addWidget(self.tools_title)
        self._i18n_buttons.append((self.tools_title, "viewer.tools_title",
                                   "viewer.tools_tip"))

        # ⇲ Размер: мышью задать размер картинки в окне предпросмотра (v0.8.6)
        self.btn_resize = QToolButton()
        self.btn_resize.setText(tr("viewer.resize"))
        self.btn_resize.setCheckable(True)
        self.btn_resize.setToolTip(tr("viewer.resize_tip"))
        self.btn_resize.setEnabled(False)   # включится, когда картинка показана
        self.btn_resize.toggled.connect(self._on_resize_toggled)
        tools_lay.addWidget(self.btn_resize)
        self._i18n_buttons.append((self.btn_resize, "viewer.resize", "viewer.resize_tip"))
        # 💾 Сохранить: появляется только в режиме изменения размера (v0.8.6)
        self.btn_resize_save = btn("viewer.resize_save", "viewer.resize_save_tip",
                                   self._on_resize_save, lay=tools_lay)
        self.btn_resize_save.setVisible(False)
        tools_lay.addWidget(vline())
        # ✂ Обрезать: выделение мышью по картинке, как в XnView (v0.8.7)
        self.btn_crop = QToolButton()
        self.btn_crop.setText(tr("viewer.crop"))
        self.btn_crop.setCheckable(True)
        self.btn_crop.setToolTip(tr("viewer.crop_tip"))
        self.btn_crop.setEnabled(False)   # включится, когда картинка показана
        self.btn_crop.toggled.connect(self._on_crop_toggled)
        tools_lay.addWidget(self.btn_crop)
        self._i18n_buttons.append((self.btn_crop, "viewer.crop", "viewer.crop_tip"))
        # три кнопки режима обрезки — видны только в режиме (v0.8.7):
        # как в XnView — «Обрезать», «Сохранить выделенную область как…»
        # и «Обрезать, Сохранить и перейти к следующему»
        self.btn_crop_save = btn("viewer.crop_save", "viewer.crop_save_tip",
                                 self._on_crop_apply, lay=tools_lay)
        self.btn_crop_save.setVisible(False)
        self.btn_crop_saveas = btn("viewer.crop_saveas", "viewer.crop_saveas_tip",
                                   self._on_crop_save_as, lay=tools_lay)
        self.btn_crop_saveas.setVisible(False)
        # 🪣 Закрасить: залить выделенное цветом пипетки (v0.8.8) — четвёртая
        # кнопка режима обрезки, видна только в режиме
        self.btn_fill = btn("viewer.fill", "viewer.fill_tip", self._on_fill_apply,
                            lay=tools_lay)
        self.btn_fill.setVisible(False)
        # 🧽 Убрать в выделении: ватермарки в выделении обрезки через LaMa
        # (v0.8.22, пожелание: «сделай возможность удалять ватермарки из
        # выделения на картинке») — та же рамка, что у обрезки; видна
        # только в режиме, между «🪣 Закрасить» и «✂▶ К следующему»
        self.btn_wm_sel = btn("viewer.wm_sel", "viewer.wm_sel_tip",
                              self._wm_sel_start, lay=tools_lay)
        self.btn_wm_sel.setVisible(False)
        self.btn_crop_next = btn("viewer.crop_next", "viewer.crop_next_tip",
                                 self._on_crop_apply_next, lay=tools_lay)
        self.btn_crop_next.setVisible(False)
        tools_lay.addWidget(vline())
        # 💧 Пипетка: цвет пикселя по клику (v0.8.8); правый клик по картинке
        # берёт цвет в ЛЮБОМ режиме — образец нужен кнопке «🪣 Закрасить»
        self.btn_picker = QToolButton()
        self.btn_picker.setText(tr("viewer.picker"))
        self.btn_picker.setCheckable(True)
        self.btn_picker.setToolTip(tr("viewer.picker_tip"))
        self.btn_picker.setEnabled(False)   # включится, когда картинка показана
        self.btn_picker.toggled.connect(self._on_picker_toggled)
        tools_lay.addWidget(self.btn_picker)
        self._i18n_buttons.append((self.btn_picker, "viewer.picker", "viewer.picker_tip"))
        # образец взятого цвета: цветной квадрат + HEX — появляется
        # после первого взятого цвета и живёт до конца сессии
        self.picker_swatch = QLabel()
        self.picker_swatch.setFixedSize(18, 18)
        self.picker_swatch.setVisible(False)
        tools_lay.addWidget(self.picker_swatch)
        self.picker_hex = QLabel("")
        self.picker_hex.setStyleSheet("color: #666;")
        self.picker_hex.setVisible(False)
        tools_lay.addWidget(self.picker_hex)
        self._i18n_buttons.append((self.picker_swatch, None, "viewer.picker_chip_tip"))
        self._i18n_buttons.append((self.picker_hex, None, "viewer.picker_chip_tip"))
        tools_lay.addWidget(vline())
        # 🪄 Удалить фон (rembg) и 🧽 Убрать водяные знаки (Florence-2 + LaMa)
        # — переехали с верхней панели на панель инструментов (v0.8.18,
        # пожелание: «убрать фон и водяные знаки перемести на панель ниже.
        # они мешают отображению поиска»): на верхней панели они теснили
        # поле поиска, здесь — рядом с инструментами картинки. Работают по
        # выделенным файлам ленты (показанная картинка не обязательна),
        # поэтому в отличие от Размер/Обрезать/Пипетка доступны всегда.
        self.btn_rembg = btn("viewer.rembg", "viewer.rembg_tip",
                             self._on_rembg_button, lay=tools_lay)
        self.btn_wm = btn("viewer.wm", "viewer.wm_tip",
                          self._on_wm_button, lay=tools_lay)
        # ✨ Улучшить (Real-ESRGAN, v0.8.24) — третий модуль на панели
        # инструментов: по выделенным файлам ленты, как соседние
        self.btn_up = btn("viewer.up", "viewer.up_tip",
                          self._on_up_button, lay=tools_lay)
        tools_lay.addStretch(1)

        # --- список миниатюр ---
        self.list = _ThumbList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumWidth(THUMB + 34)  # ширина задаётся сплиттером — панель растягивается мышью
        # редактор переименования: поле с выделением имени без расширения (v0.7.17)
        self.list.setItemDelegate(_ThumbDelegate(self.list))
        # drag'n'drop: выделенные файлы перетаскиваются мышью в другие приложения
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragOnly)
        self.list.setToolTip(tr("viewer.dnd_tip"))
        # запасной перенос без драга: Ctrl+C или правый клик — файлы в буфер обмена
        sc_copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.list)
        sc_copy.activated.connect(self.copy_selected_files)
        # Ctrl+A — выделить всё: явная горячая клавиша (работает и без неё, но
        # так не зависит от темы/платформы) + отметка в журнале
        sc_all = QShortcut(QKeySequence(QKeySequence.StandardKey.SelectAll), self.list)
        sc_all.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_all.activated.connect(self._select_all_files)
        # Delete — переместить выделенные файлы в корзину. Контекст WidgetShortcut:
        # срабатывает только когда фокус в списке — Delete в поле поиска
        # продолжает работать как обычно
        sc_del = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.list)
        sc_del.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_del.activated.connect(self.delete_selected_files)
        # F2 — переименовать файл под курсором (v0.7.17). Контекст WidgetShortcut:
        # пока открыт редактор имени (QLineEdit), F2 в нём печатает символ «2»,
        # лента ничего не перехватывает
        sc_ren = QShortcut(QKeySequence("F2"), self.list)
        sc_ren.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc_ren.activated.connect(self.rename_current_file)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_context_menu)
        self.list.currentRowChanged.connect(self._show_index)
        self.list.itemDoubleClicked.connect(
            lambda item: QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
        )
        # двойной клик по ИМЕНИ плитки — переименование, по картинке — открытие
        # (обработка сигнала из _ThumbList, v0.7.17)
        self.list.nameDoubleClicked.connect(self._begin_rename)
        # правка имени завершена (Enter/клик мимо): имя из редактора → на диск.
        # itemChanged приходит и от выставления миниатюр — там текст равен имени
        # из пути, и хендлер выйдет сразу (см. _on_item_changed)
        self.list.itemChanged.connect(self._on_item_changed)
        # прокрутили список — надо догрузить миниатюры новых видимых строк
        self.list.verticalScrollBar().valueChanged.connect(self._schedule_visible_thumbs)

        # --- дерево дисков и папок (левая панель) ---
        # _Tree принимает перетаскиваемые из ленты файлы — drop на папку
        # дерева переносит туда все выделенные файлы (v0.8.5)
        self.tree = _Tree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemExpanded.connect(self._populate_children)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        # правый клик в дереве — добавить/убрать папку в избранном (v0.7.9)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)

        tree_panel = QWidget()
        tree_lay = QVBoxLayout(tree_panel)
        tree_lay.setContentsMargins(0, 0, 0, 0)
        tree_lay.setSpacing(0)
        tree_hdr = QHBoxLayout()
        tree_hdr.setContentsMargins(8, 6, 4, 2)
        self.tree_hdr_label = QLabel(tr("viewer.drives"))
        tree_hdr.addWidget(self.tree_hdr_label)
        tree_hdr.addStretch(1)
        # ☆/★ — добавить/убрать ТЕКУЩУЮ папку (открытую во вкладке) в избранное
        self.btn_fav = QToolButton()
        self.btn_fav.setAutoRaise(True)
        self.btn_fav.clicked.connect(self._on_fav_button)
        tree_hdr.addWidget(self.btn_fav)
        btn_refresh = QToolButton()
        btn_refresh.setText("⟳")
        btn_refresh.setToolTip(tr("viewer.refresh_tip"))
        btn_refresh.setAutoRaise(True)
        btn_refresh.clicked.connect(self._on_tree_refresh_clicked)
        tree_hdr.addWidget(btn_refresh)
        tree_lay.addLayout(tree_hdr)

        # --- поиск папок: поле над деревом «Диски и папки» ---
        self.folder_search = QLineEdit()
        self.folder_search.setPlaceholderText(tr("viewer.folders_search_ph"))
        self.folder_search.setClearButtonEnabled(True)
        self.folder_search.setToolTip(tr("viewer.folders_search_tip"))
        self.folder_search.textChanged.connect(self._on_folder_search_text_changed)
        self.folder_search.returnPressed.connect(self._open_first_folder_result)
        fs_lay = QHBoxLayout()
        fs_lay.setContentsMargins(8, 2, 8, 2)
        fs_lay.addWidget(self.folder_search)
        tree_lay.addLayout(fs_lay)

        # строка под полем: «Поиск папок…» / «Найдено папок: N» — видна только в поиске
        self.tree_info = QLabel("")
        self.tree_info.setStyleSheet("color: #666;")
        self.tree_info.setContentsMargins(8, 0, 8, 0)
        self.tree_info.hide()
        tree_lay.addWidget(self.tree_info)
        tree_lay.addWidget(self.tree, 1)

        # --- область просмотра ---
        # _ResizeView — тот же просмотр с «шахматкой» (v0.7.16) плюс рукоятки
        # изменения размера мышью (v0.8.6): рамка, угол и края, бейдж размера
        self.view_label = _ResizeView("…")
        self.view_label.setAlignment(Qt.AlignCenter)
        self.view_label.setBackgroundRole(QPalette.ColorRole.Dark)
        self.view_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.view_label.setScaledContents(False)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.view_label)
        self.scroll.setWidgetResizable(True)
        self.scroll.setBackgroundRole(QPalette.ColorRole.Dark)
        self.scroll.viewport().installEventFilter(self)  # Ctrl+колесо — зум
        # перетаскивание рукояток рамки ресайза (v0.8.6): захват, движение
        # и отпускание мыши приходят сигналами из _ResizeView
        self.view_label.resize_started.connect(self._on_resize_start)
        self.view_label.resize_dragged.connect(self._on_resize_drag)
        self.view_label.resize_finished.connect(self._on_resize_release)
        # выделение обрезки меняет сам вью — вьюеру нужен только статус (v0.8.7)
        self.view_label.crop_selection_changed.connect(self._on_crop_selection_changed)
        # пипетка (v0.8.8): клик/правый клик — взять цвет, наведение —
        # живой цвет под курсором в статусе
        self.view_label.picker_pick.connect(self._on_picker_pick)
        self.view_label.picker_hover.connect(self._on_picker_hover)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        # панель инструментов картинки — сразу под верхней панелью (v0.8.9)
        layout.addWidget(self.tools_panel)
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
        # перетаскивание разделителя сужает/расширяет ленту миниатюр;
        # размеры панелей запоминаются между запусками
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        saved_split = QSettings("ImageHunter", "ImageHunter").value("viewer/splitter")
        if saved_split is not None:
            try:
                self.splitter.restoreState(saved_split)
            except (TypeError, RuntimeError):
                pass
        layout.addWidget(self.splitter, 1)

        self._thumb_signals = _ThumbSignals()
        self._thumb_signals.ready.connect(self._on_thumb_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        # фоновый полноэкранный просмотр: счётчик незавершённых задач —
        # по нему включается/выключается курсор занятости
        self._view_signals = _ViewSignals()
        self._view_signals.ready.connect(self._on_view_ready)
        self._view_inflight = 0
        self._view_busy = False
        # фоновое чтение GIF: анимация строится из памяти (v0.7.11)
        self._gif_signals = _GifSignals()
        self._gif_signals.ready.connect(self._on_gif_ready)
        # применяем миниатюры пачками по таймеру: сотни setIcon подряд
        # заставляют список перестраивать раскладку на каждую иконку
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(120)
        self._thumb_timer.timeout.connect(self._flush_thumbs)
        # поиск по имени: сигналы + дебаунс набора (350 мс)
        self._search_signals = _SearchSignals()
        self._search_signals.batch.connect(self._on_search_batch)
        self._search_signals.done.connect(self._on_search_done)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._start_search_now)
        # фильтр папок в дереве: короткий дебаунс набора (300 мс) — сам фильтр
        # мгновенный, пауза лишь чтобы не догружать ветви на каждую букву
        self._fs_timer = QTimer(self)
        self._fs_timer.setSingleShot(True)
        self._fs_timer.setInterval(300)
        self._fs_timer.timeout.connect(self._apply_folder_filter)
        # ленивые миниатюры: пересчёт видимых строк не чаще раза в 120 мс
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(120)
        self._visible_timer.timeout.connect(self._queue_visible_thumbs)
        # рескейл «по размеру окна» — после паузы в ресайзе (v0.7.11):
        # SmoothTransformation на большом фото занимает десятки миллисекунд,
        # и на каждый пиксель перетаскивания края окна они складывались
        # в заметные подлагивания; теперь картинка подгоняется один раз —
        # когда окно перестало меняться
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(80)
        self._resize_timer.timeout.connect(self._apply_mode)
        # асинхронное чтение папок и дерева: скан по сети не должен
        # останавливать интерфейс (v0.7.2)
        self._scan_signals = _ScanSignals()
        self._scan_signals.done.connect(self._on_scan_done)
        self._subdir_signals = _SubdirsSignals()
        self._subdir_signals.ready.connect(self._on_subdirs_ready)
        # диски: перечисление фоном + кэш последнего списка (v0.7.14)
        self._drives_signals = _DrivesSignals()
        self._drives_signals.ready.connect(self._on_drives_ready)
        self._drives_cache: list[tuple[str, str, int, int]] = []
        self._delete_signals = _DeleteSignals()
        self._delete_signals.done.connect(self._on_delete_done)
        # перенос выделенных файлов в папку дерева (v0.8.5): одна фоновая
        # задача за раз — второй drop во время первого ждёт, не множится
        self._move_signals = _MoveSignals()
        self._move_signals.done.connect(self._on_move_done)
        self._move_inflight = False
        self._move_t0 = 0.0
        # узкий пул для сетевых файлов: пока сервер подвис, ждут одна-две
        # задачи — локальные миниатюры продолжают грузиться (v0.7.2)
        self._net_pool = QThreadPool(self)
        self._net_pool.setMaxThreadCount(2)
        self._tree_token = 0
        self._sync_seq = 0   # поколение асинхронной прогулки — для отмены
        self._scan_sync_tree = False
        self._scan_restore = False
        self._delete_perm = False
        self._delete_phase = 0
        self._delete_t0 = 0.0

        # удаление фона (rembg): сигналы фоновых задач + состояние (v0.7.12)
        self._rembg_signals = rembg_manager.RembgSignals()
        self._rembg_signals.install_done.connect(self._on_rembg_install_done)
        self._rembg_signals.uninstall_done.connect(self._on_rembg_uninstall_done)
        self._rembg_signals.file_done.connect(self._on_rembg_file_done)
        self._rembg_signals.batch_done.connect(self._on_rembg_batch_done)
        # начало файла — процесс в строке статуса (v0.8.20)
        self._rembg_signals.file_start.connect(self._on_rembg_file_start)
        # жизнь модели и возврат оригиналов — статусная строка рассказывает
        # про модуль целиком: готовится, качается (сколько из скольких), готова
        self._rembg_signals.model_prepare.connect(self._on_rembg_model_prepare)
        self._rembg_signals.model_ready.connect(self._on_rembg_model_ready)
        self._rembg_signals.model_dl_start.connect(self._on_rembg_model_dl_start)
        self._rembg_signals.model_dl_progress.connect(
            self._on_rembg_model_dl_progress)
        self._rembg_signals.model_dl_done.connect(self._on_rembg_model_dl_done)
        self._rembg_signals.revert_done.connect(self._on_rembg_revert_done)
        self._rembg_signals.update_done.connect(self._on_rembg_update_done)
        self._rembg_busy = False       # pip/обработка уже идут — второй запуск не нужен
        self._rembg_pending: list[str] | None = None   # очередь после установки
        self._rembg_ok = 0
        self._rembg_fail = 0
        self._rembg_total = 0
        self._rembg_t0 = 0.0
        self._rembg_results: list[str] = []   # результаты пачки (выбор сохранить/вернуть)
        self._rembg_choice: QDialog | None = None   # открытый диалог выбора
        self._dl_model = ""                   # какая модель сейчас качается
        saved_model = QSettings("ImageHunter", "ImageHunter").value(
            rembg_manager.MODEL_KEY, rembg_manager.DEFAULT_MODEL, type=str)
        # в настройках могла остаться модель, которой больше нет в списке
        self._rembg_model = (saved_model if saved_model in
                             {m for m, _k in rembg_manager.REMBG_MODELS}
                             else rembg_manager.DEFAULT_MODEL)

        # водяные знаки (Florence-2 + LaMa/IOPaint): сигналы + состояние (v0.8.11)
        self._wm_signals = watermark_manager.WatermarkSignals()
        self._wm_signals.install_done.connect(self._on_wm_install_done)
        self._wm_signals.uninstall_done.connect(self._on_wm_uninstall_done)
        self._wm_signals.file_done.connect(self._on_wm_file_done)
        self._wm_signals.batch_done.connect(self._on_wm_batch_done)
        # процесс внутри пачки — в строку статуса (v0.8.20, пожелание:
        # «видеть в строке статуса процесс и/или статус работы модулей,
        # особенно модуля удаления ватермарков»)
        self._wm_signals.file_start.connect(self._on_wm_file_start)
        self._wm_signals.phase.connect(self._on_wm_phase)
        self._wm_signals.model_dl_start.connect(self._on_wm_model_dl_start)
        self._wm_signals.model_dl_progress.connect(self._on_wm_model_dl_progress)
        # модели готовятся/качаются при первом запуске — статус расскажет
        self._wm_signals.model_prepare.connect(self._on_wm_model_prepare)
        self._wm_signals.model_ready.connect(self._on_wm_model_ready)
        self._wm_signals.update_done.connect(self._on_wm_update_done)
        self._wm_busy = False          # pip/обработка уже идут — второй запуск не нужен
        self._wm_pending: list[str] | None = None   # очередь после установки
        # убирание по выделению (v0.8.22): продолжить после установки модуля
        # и результат, который надо открыть после пересканирования ленты
        self._wm_sel_pending = False
        self._wm_sel_open = ""
        self._wm_ok = 0
        self._wm_clean = 0             # файлы без найденных водяных знаков
        self._wm_fail = 0
        self._wm_total = 0
        self._wm_t0 = 0.0
        self._wm_idx = 0               # какой файл пачки сейчас в работе (v0.8.20)
        self._wm_dl_model = ""         # какая модель сейчас качается (v0.8.20)
        saved_wm_model = QSettings("ImageHunter", "ImageHunter").value(
            watermark_manager.MODEL_KEY, watermark_manager.DEFAULT_MODEL, type=str)
        self._wm_model = (saved_wm_model if saved_wm_model in
                          {m for m, _k in watermark_manager.FLORENCE_MODELS}
                          else watermark_manager.DEFAULT_MODEL)

        # улучшение качества (Real-ESRGAN): сигналы + состояние (v0.8.24)
        self._ups_signals = upscale_manager.UpscaleSignals()
        self._ups_signals.install_done.connect(self._on_up_install_done)
        self._ups_signals.uninstall_done.connect(self._on_up_uninstall_done)
        self._ups_signals.update_done.connect(self._on_up_update_done)
        self._ups_signals.file_done.connect(self._on_up_file_done)
        self._ups_signals.batch_done.connect(self._on_up_batch_done)
        # процесс внутри пачки — в строку статуса (v0.8.20), как у соседей
        self._ups_signals.file_start.connect(self._on_up_file_start)
        self._ups_signals.phase.connect(self._on_up_phase)
        self._ups_signals.model_dl_start.connect(self._on_up_model_dl_start)
        self._ups_signals.model_dl_progress.connect(
            self._on_up_model_dl_progress)
        self._ups_signals.model_dl_done.connect(self._on_up_model_dl_done)
        # модели готовятся/качаются при первом запуске — статус расскажет
        self._ups_signals.model_prepare.connect(self._on_up_model_prepare)
        self._ups_signals.model_ready.connect(self._on_up_model_ready)
        self._ups_signals.revert_done.connect(self._on_up_revert_done)
        self._ups_busy = False         # pip/обработка уже идут — второй запуск не нужен
        self._ups_pending: list[str] | None = None   # очередь после установки
        self._ups_ok = 0
        self._ups_fail = 0
        self._ups_total = 0
        self._ups_t0 = 0.0
        self._ups_idx = 0              # какой файл пачки сейчас в работе
        self._ups_dl_model = ""        # какие веса сейчас качаются
        self._ups_results: list[str] = []   # результаты пачки (выбор сохранить/вернуть)
        self._ups_choice: QDialog | None = None   # открытый диалог выбора
        saved_up_model = QSettings("ImageHunter", "ImageHunter").value(
            upscale_manager.MODEL_KEY, upscale_manager.DEFAULT_MODEL, type=str)
        self._ups_model = (saved_up_model if saved_up_model in
                           {m for m, _k in upscale_manager.UPSCALE_MODELS}
                           else upscale_manager.DEFAULT_MODEL)

        # избранные папки читаются до построения дерева (v0.7.9)
        self._favorites = self._load_favorites()
        self._update_fav_button()
        self.refresh_drives()
        self._restore_last_folder()
        # восстановить последний запрос поиска — каким он был перед закрытием
        last_q = QSettings("ImageHunter", "ImageHunter").value("viewer/last_query", "")
        if last_q:
            self.search_edit.setText(last_q)   # textChanged → дебаунс → автопоиск
        i18n.signals.changed.connect(self._retranslate)

    # ---------- перетрансляция при смене языка ----------

    def _retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка)."""
        for b, text_key, tip_key in self._i18n_buttons:
            if text_key is not None:
                b.setText(tr(text_key))
            b.setToolTip(tr(tip_key))
        self.search_edit.setPlaceholderText(tr("viewer.search_ph"))
        self.search_edit.setToolTip(tr("viewer.search_tip"))
        self.ignore_dash_box.setText(tr("viewer.ignore_dash"))
        self.ignore_dash_box.setToolTip(tr("viewer.ignore_dash_tip"))
        self.checker_icon.setToolTip(tr("viewer.checker_tip"))
        self.checker_slider.setToolTip(tr("viewer.checker_tip"))
        self.folder_search.setPlaceholderText(tr("viewer.folders_search_ph"))
        self.folder_search.setToolTip(tr("viewer.folders_search_tip"))
        self.list.setToolTip(tr("viewer.dnd_tip"))
        self.tree.setToolTip(tr("viewer.tree_drop_tip"))
        self.tree_hdr_label.setText(tr("viewer.drives"))
        self._update_fav_button()   # подсказка ☆/★ — на новом языке
        if not self._paths:
            self.status.setText(tr("viewer.pick"))
        # быстрые ссылки «Домой»/«Изображения» тоже переводятся; активный
        # фильтр папок применится заново к перечитанному дереву (см. refresh_drives)
        self.refresh_drives()

    # ---------- публичное ----------

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("viewer.open_dlg"), self._folder or "")
        if folder:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._cancel_search()
            self.load_folder(folder)   # скан в рабочем потоке
            self.show_in_tree(folder)  # подсветка — асинхронной прогулкой (v0.7.11)

    def show_in_tree(self, folder: str) -> None:
        """Подсветить folder в дереве без замираний (асинхронная прогулка, v0.7.6).

        Раньше «Открыть папку…» подсвечивала синхронно (_sync_tree): каждый
        уровень пути платил скан в GUI-потоке — на сетевом диске с подвисшим
        сервером окно замерало на сетевой тайм-аут за каждый уровень.
        """
        self._sync_tree_async(folder)

    def current_folder(self) -> str:
        """Папка, открытая сейчас во вкладке (используется для сохранения WebP)."""
        return self._folder

    def save_state(self) -> None:
        """Запомнить последнюю папку и запрос поиска — восстановятся при старте."""
        st = QSettings("ImageHunter", "ImageHunter")
        if self._folder:
            st.setValue("viewer/last_folder", self._folder)
        st.setValue("viewer/last_query", self.search_edit.text().strip())

    def refresh(self) -> None:
        """Пересканировать текущую папку (например, после сохранения в неё WebP).

        Скан идёт в рабочем потоке (см. load_folder) — пропавшая папка
        или подвисшая сеть не замораживают окно. Активный поиск по имени
        не сбрасывается: вместо простой ленты заново запускается поиск
        (как при клике по дереву) — новая порция файлов дописывается
        в ту же выдачу, вводить запрос и жать Enter заново не нужно (v0.7.5)."""
        if not self._folder:
            return
        if self.search_edit.text().strip():
            self._start_search_now()   # фильтр активен — перечитываем выдачей поиска
        else:
            self.load_folder(self._folder)

    # ---------- запасной перенос файлов: через буфер обмена ----------

    def copy_selected_files(self) -> None:
        """Выделенные файлы — в буфер обмена, без перетаскивания.

        Работает даже там, где драг мышью почему-то не срабатывает:
        вставить можно в Проводник, браузер или письмо (Ctrl+V)."""
        paths = self.list.selected_paths()
        if not paths:
            self.status.setText(tr("viewer.copy_nothing"))
            return
        mime = make_file_urls_mime(paths)
        mime.setText("\n".join(paths))
        QApplication.clipboard().setMimeData(mime)
        applog.event("log.event.copy_files", n=len(paths))
        self.status.setText(tr("viewer.copied_status", n=len(paths)))

    def _select_all_files(self) -> None:
        """Ctrl+A на ленте миниатюр: выделить всё и отметить в журнале."""
        self.list.selectAll()
        n = len(self.list.selectedItems())
        if n:
            applog.event("log.event.select_all", n=n)

    def delete_selected_files(self) -> None:
        """Удалить выделенные файлы (Delete или контекстное меню).

        По умолчанию — в корзину (восстановимо). На дисках без корзины
        (сетевые, часть съёмных) сразу предлагается окончательное удаление;
        если корзина отказала — тоже спрашивается второе подтверждение.
        Каждая неудача пишется в журнал с причиной. Само удаление идёт в
        рабочем потоке (_DeleteTask): по сети файл может удаляться секунды,
        а на подвисшем сервере — сетевой тайм-аут целиком, и окно не должно
        замереть «Не отвечает» посреди диалога (v0.7.2). При активном
        поиске по имени выдача после удаления пересобирается заново
        (v0.8.10) — как после переноса (v0.8.5)."""
        items = [it for it in self.list.selectedItems() if it.data(Qt.UserRole)]
        if not items:
            self.status.setText(tr("viewer.del_nothing"))
            return
        paths = [self._paths[self.list.row(it)] for it in items]
        # диск без корзины? честнее сразу спросить про окончательное удаление
        force_perm = all(_drive_has_trash(p) is False for p in paths)
        if force_perm:
            ans = QMessageBox.question(
                self, tr("viewer.del_perm_title"),
                tr("viewer.del_perm_confirm", n=len(items)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)   # по умолчанию — безопасное «Нет»
        else:
            ans = QMessageBox.question(
                self, tr("viewer.del_title"), tr("viewer.del_confirm", n=len(items)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._delete_perm = force_perm
        self._start_delete(paths, phase=1)

    def _start_delete(self, paths: list[str], phase: int) -> None:
        """Запустить фазу удаления в рабочем потоке (1 — корзина, 2 — навсегда).

        Сетевые пути — через узкий пул (v0.8.19, _io_pool): удаление не
        должно плодить параллельные запросы к davfs2 и делить с ним слоты."""
        self._delete_phase = phase
        self._delete_t0 = time.perf_counter()
        self._set_view_busy(True)
        self.status.setText(tr("viewer.delete_busy"))
        self._io_pool(*paths).start(
            _DeleteTask(paths, perm=(phase == 2 or self._delete_perm),
                        phase=phase, signals=self._delete_signals))

    def _on_delete_done(self, phase: int, results: list) -> None:
        """Файлы удалены в фоне — обновить ленту; при отказе корзины спросить
        про окончательное удаление и запустить вторую фазу."""
        trash_n = perm_n = failed_n = 0
        # как именно удаляли: фаза 1 с заранее известным «навсегда»
        # (диск без корзины, self._delete_perm) — тоже окончательное;
        # счёт по номеру фазы называл такое удаление «в корзину»
        # и в статусе, и в журнале (v0.7.11)
        perm = (phase == 2) or self._delete_perm
        retry: list[str] = []               # корзина отказала — попытка 2
        for path, ok, err in results:
            if ok:
                if perm:
                    perm_n += 1
                else:
                    trash_n += 1
                self._remove_row_by_path(path)
            else:
                applog.error(tr("log.event.trash_err", path=path, err=err))
                failed_n += 1
                if not perm:
                    retry.append(path)
        if not perm and retry:
            self._set_view_busy(False)
            ans = QMessageBox.question(
                self, tr("viewer.del_perm_ask_title"),
                tr("viewer.del_perm_ask", n=len(retry)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                self._start_delete(retry, phase=2)
                return
        self._finish_delete(trash_n, perm_n, failed_n)

    def _finish_delete(self, trash_n: int, perm_n: int, failed_n: int) -> None:
        """Итог удаления: события в журнал, статус, порядок строк в ленте.

        При активном поиске по имени выдача не просто худеет, а
        пересобирается заново (как после переноса, v0.8.5): удалённые
        файлы не числятся найденными, счётчик «Найдено: N» честный,
        а поиск, обрезанный по пределу 5000, добирает следующие находки
        (v0.8.10)."""
        self._delete_phase = 0
        self._set_view_busy(False)
        done = trash_n + perm_n
        if done:
            if trash_n:
                applog.event("log.event.trash", n=trash_n,
                             folder=self._folder or "—")
            if perm_n:
                applog.event("log.event.delete_perm", n=perm_n,
                             folder=self._folder or "—")
            if self.search_edit.text().strip():
                # активен поиск по имени: пересобрать выдачу — удалённые
                # файлы не должны числиться найденными (принцип переноса,
                # v0.8.5); курсор встанет на первую плитку выдачи
                self._start_search_now()
            else:
                # строки сместились — кэш миниатюр по номерам строк больше не верен
                self._list_rows_changed()
        if failed_n:
            self.status.setText(tr("viewer.del_done_err", n=done, m=failed_n))
        elif perm_n and trash_n:
            self.status.setText(tr("viewer.del_done_mixed",
                                   n=done, t=trash_n, p=perm_n))
        elif perm_n:
            self.status.setText(tr("viewer.del_done_perm", n=perm_n))
        elif done:
            self.status.setText(tr("viewer.del_done", n=done))
        if done or failed_n:
            applog.event("log.event.timing", op=tr("perf.op.delete_files"),
                         ms=round((time.perf_counter() - self._delete_t0) * 1000),
                         extra=applog.extra(trash=trash_n, perm=perm_n,
                                            fail=failed_n))

    def _list_rows_changed(self) -> None:
        """Строки ленты убыли/сменились: кэши по номерам строк больше не верны."""
        self._pending_thumbs.clear()
        self._pending_dims.clear()
        self._thumb_queued.clear()
        self._thumb_done_rows.clear()
        self._schedule_visible_thumbs()
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        elif not self.list.count():
            self._pixmap = None
            self._movie = None
            self._view_text(tr("viewer.no_images"))

    def _remove_row_by_path(self, path: str) -> None:
        """Убрать удалённый файл из ленты и из _paths (строки смещаются)."""
        norm = os.path.normcase(os.path.normpath(path))
        for r in range(self.list.count()):
            it = self.list.item(r)
            p = it.data(Qt.UserRole)
            if p and os.path.normcase(os.path.normpath(p)) == norm:
                self.list.takeItem(r)
                break
        keep = [i for i, p in enumerate(self._paths)
                if os.path.normcase(os.path.normpath(p)) != norm]
        self._paths = [self._paths[i] for i in keep]
        self._meta = [self._meta[i] for i in keep]

    # ---------- перенос выделенных файлов в папку дерева (drop; v0.8.5) ----------

    def move_files_to(self, paths: list[str], target: str) -> None:
        """Перенести файлы (из drop на дерево) в папку target.

        Файлы, уже лежащие в target, отсекаются сразу (по каталогам —
        без обращения к диску); остальное считает _MoveTask в рабочем
        потоке: shutil.move по сети может подвиснуть (принцип v0.7.2).
        Пока задача едет, новый drop ждёт — статус честно об этом скажет.
        """
        if self._move_inflight:
            self.status.setText(tr("viewer.move_busy"))
            return
        paths = [p for p in paths if p]
        if not paths:
            self.status.setText(tr("viewer.move_nothing"))
            return
        target_n = os.path.normcase(os.path.normpath(target))
        todo = [p for p in paths
                if os.path.normcase(os.path.normpath(os.path.dirname(p)))
                != target_n]
        if not todo:
            self.status.setText(tr("viewer.move_same_folder"))
            return
        self._move_inflight = True
        self._move_t0 = time.perf_counter()
        tgt = os.path.basename(target) or target
        self.status.setText(tr("viewer.moving", n=len(todo), target=tgt))
        applog.event("log.event.move_start", n=len(todo), target=target,
                     names=", ".join(os.path.basename(p) for p in todo[:3]))
        # перенос по сети — через узкий пул (v0.8.19): не плодим параллельные
        # запросы к davfs2 и не делим с ним слоты
        self._io_pool(target, *todo).start(
            _MoveTask(todo, target, self._move_signals))

    def _on_move_done(self, ok: int, skipped: int, failed: int,
                      errors: list, moved: list, target: str) -> None:
        """Перенос завершён в фоне: статус, журнал, лента без уехавших файлов."""
        self._move_inflight = False
        tgt = os.path.basename(target) or target
        if failed:
            self.status.setText(tr("viewer.move_done_err", n=ok, m=failed))
        elif ok:
            self.status.setText(tr("viewer.move_done", n=ok, target=tgt))
        else:
            self.status.setText(tr("viewer.move_none"))
        for name, err in errors:
            applog.error(tr("log.event.move_err", path=name, err=err))
        if ok:
            applog.event("log.event.move_done", n=ok, target=target,
                         skip=skipped)
            applog.event("log.event.timing", op=tr("perf.op.move_files"),
                         ms=round((time.perf_counter() - self._move_t0) * 1000),
                         extra=applog.extra(ok=ok, skip=skipped, fail=failed))
            if self.search_edit.text().strip():
                # активен поиск по имени: пересобрать результаты — уехавшие
                # файлы не должны числиться найденными
                self._start_search_now()
            else:
                for p in moved:
                    self._remove_row_by_path(p)
                if moved:
                    self._list_rows_changed()

    # ---------- переименование файла (F2, двойной клик по имени, меню; v0.7.17) ----------

    def _item_by_path(self, path: str) -> QListWidgetItem | None:
        """Найти плитку по полному пути (сравнение без учёта регистра/разделителей)."""
        norm = os.path.normcase(os.path.normpath(path))
        for r in range(self.list.count()):
            it = self.list.item(r)
            p = it.data(Qt.UserRole)
            if p and os.path.normcase(os.path.normpath(p)) == norm:
                return it
        return None

    def rename_current_file(self) -> None:
        """F2 или пункт меню «Переименовать»: править имя текущей плитки.

        Как в Проводнике: из выделенных переименовывается тот файл, на
        котором курсор, — пачкам имена не раздают."""
        item = self.list.currentItem()
        if item is None or not item.data(Qt.UserRole):
            self.status.setText(tr("viewer.rename_nothing"))
            return
        self._begin_rename(item)

    def _begin_rename(self, item: QListWidgetItem) -> None:
        """Открыть редактор имени у плитки (двойной клик по имени / F2 / меню).

        Программный editItem() при NoEditTriggers отказывает («edit: editing
        failed»), а включать триггеры насовсем нельзя: двойной клик по
        картинке должен открывать файл, а не править имя. Триггер двойного
        клика включается только на время вызова editItem и сразу
        возвращается как был. Qt::ItemIsEditable у плиток изначально нет —
        ставим тем же жестом: всё равно редактор открывается только явно."""
        if item is None or not item.data(Qt.UserRole):
            return
        if self._rename_inflight:
            # предыдущее переименование ещё едет (обычно это доли секунды,
            # на подвисшем сетевом диске — дольше): не плодим очередь
            self.status.setText(tr("viewer.rename_busy"))
            return
        self.list.setCurrentItem(item)
        self.list.scrollToItem(item)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        try:
            self.list.editItem(item)
        finally:
            self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Правка имени завершена (Enter, клик мимо): имя из редактора — на диск.

        itemChanged приходит и от выставления миниатюр, и от наших же
        обновлений плитки — во всех этих случаях текст плитки равен имени из
        её пути, и хендлер выходит сразу. Дальше идёт только настоящий ввод
        пользователя, пока задача переименования не едет."""
        if self._rename_inflight or item is None:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        old_name = os.path.basename(path)
        new_name = _clean_rename_name(item.text())
        if new_name == old_name:
            if item.text() != old_name:   # «имя.jpg   » — вернуть ровное имя
                item.setText(old_name)
            return
        if not _name_is_allowed(new_name):
            # пустое имя или запрещённые в Windows символы — на диск не несём
            item.setText(old_name)   # itemChanged вернётся сюда и выйдет по равенству
            self.status.setText(tr("viewer.rename_invalid"))
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        self._rename_inflight = True
        self.status.setText(tr("viewer.rename_progress", name=new_name))
        # os.rename по сети может держать тайм-аут — только в рабочем потоке;
        # сетевые пути — через узкий пул (v0.8.19)
        self._io_pool(path, new_path).start(
            _RenameTask(path, new_path, self._rename_signals))

    def _on_rename_done(self, old: str, new: str, ok: bool, err: str) -> None:
        """Файл переименован в фоне — обновить плитку, _paths и статус.

        Флаг _rename_inflight держится до самого конца: оба обновления
        плитки (путь и текст) дают itemChanged, и каждый из них должен быть
        проигнорирован хендлером правки."""
        old_name, new_name = os.path.basename(old), os.path.basename(new)
        item = self._item_by_path(old)
        if ok:
            if item is not None:
                item.setData(Qt.UserRole, new)
                item.setText(new_name)
                # подсказка как при построении ленты: в показанных результатах
                # поиска — путь от папки (как _on_search_batch), иначе имя
                if self.search_edit.text().strip():
                    try:
                        item.setToolTip(os.path.relpath(new, self._folder)
                                        if self._folder else new_name)
                    except ValueError:
                        item.setToolTip(new_name)
                else:
                    item.setToolTip(new_name)
            # строка осталась на месте — достаточно заменить путь
            norm = os.path.normcase(os.path.normpath(old))
            for i, p in enumerate(self._paths):
                if os.path.normcase(os.path.normpath(p)) == norm:
                    self._paths[i] = new
                    break
            if item is not None and self.list.row(item) == self.list.currentRow():
                # переименовали открытую картинку — имя в статусе просмотра
                if self._pixmap is not None:
                    self._set_view_status(new, self.list.currentRow(),
                                          self._pixmap.size())
                elif self._movie is not None:
                    self._set_view_status(new, self.list.currentRow(),
                                          self._movie.currentPixmap().size())
            self.status.setText(tr("viewer.rename_done", old=old_name, new=new_name))
            applog.event("log.event.rename", old=old_name, new=new_name)
        else:
            if item is not None:
                item.setText(old_name)   # имя не уехало — вернуть старое
            self.status.setText(tr("viewer.rename_err", name=old_name, err=err))
            applog.error(tr("log.event.rename_err", old=old_name, err=err))
        self._rename_inflight = False

    def _build_list_menu(self) -> tuple[QMenu, dict[str, object]]:
        """Собрать меню ленты (без exec — тест проверяет состав напрямую).

        Управление самим модулем rembg (установка, удаление, выбор модели)
        с v0.8.2 живёт в меню «Модули» главного окна; здесь осталась только
        файловая операция «Удалить фон» (с установкой «на ходу», если
        модуля ещё нет)."""
        menu = QMenu(self)
        acts: dict[str, object] = {}
        acts["open"] = menu.addAction(tr("viewer.ctx_open"))
        acts["copy"] = menu.addAction(tr("viewer.ctx_copy"))
        acts["copy"].setToolTip(tr("viewer.ctx_copy_tip"))
        acts["rename"] = menu.addAction(tr("viewer.ctx_rename"))
        acts["rename"].setToolTip(tr("viewer.ctx_rename_tip"))
        acts["bg"] = menu.addAction(tr("viewer.rembg"))
        acts["bg"].setToolTip(tr("viewer.rembg_tip"))
        acts["wm"] = menu.addAction(tr("viewer.wm"))
        acts["wm"].setToolTip(tr("viewer.wm_tip"))
        acts["up"] = menu.addAction(tr("viewer.up"))
        acts["up"].setToolTip(tr("viewer.up_tip"))
        acts["del"] = menu.addAction(tr("viewer.ctx_delete"))
        acts["del"].setToolTip(tr("viewer.ctx_delete_tip"))
        return menu, acts

    def _list_context_menu(self, pos) -> None:
        """Правый клик на ленте: открыть / копировать / переименовать / фон / удалить."""
        menu, acts = self._build_list_menu()
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is acts.get("open"):
            item = self.list.currentItem()
            if item is not None and item.data(Qt.UserRole):
                QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
        elif chosen is acts.get("copy"):
            self.copy_selected_files()
        elif chosen is acts.get("rename"):
            self.rename_current_file()
        elif chosen is acts.get("bg"):
            self._on_rembg_button()
        elif chosen is acts.get("wm"):
            self._on_wm_button()
        elif chosen is acts.get("up"):
            self._on_up_button()
        elif chosen is acts.get("del"):
            self.delete_selected_files()

    # ---------- модуль rembg: публичный доступ для меню «Модули» (v0.8.2) ----------

    def rembg_is_installed(self) -> bool:
        """Установлен ли модуль (меню «Модули» строит по этому пункты)."""
        return rembg_manager.is_installed()

    def rembg_is_busy(self) -> bool:
        """Идёт ли pip-установка/удаление или обработка пачки (guard меню)."""
        return self._rembg_busy

    def rembg_current_model(self) -> str:
        """Выбранная модель — для галочки в меню «Модули»."""
        return self._rembg_model

    def rembg_install(self) -> None:
        """Установить модуль из меню «Модули» (без отложенной пачки файлов)."""
        self._rembg_start_install()

    def rembg_uninstall(self) -> None:
        """Удалить модуль и модели из меню «Модули» (с подтверждением)."""
        self._rembg_start_uninstall()

    def rembg_set_model(self, model_id: str) -> None:
        """Выбрать модель из меню «Модули» (запоминается в настройках)."""
        self._on_rembg_model(model_id)

    def rembg_update(self) -> None:
        """Обновить установленный модуль из меню «Модули» (v0.8.15).

        Версия rembg сверяется с PyPI и обновляется в фоне; guard тот же,
        что у установки/удаления — два pip-а одновременно не запускаются.
        """
        if self._rembg_busy:
            self.status.setText(tr("viewer.rembg_busy"))
            return
        if not rembg_manager.is_installed():
            return   # меню показывает пункт только у установленного модуля
        self._rembg_busy = True
        modstatus.report("rembg", tr("viewer.rembg_updating"), frac=-1.0)
        applog.event("log.event.rembg_update_start")
        QThreadPool.globalInstance().start(
            rembg_manager.UpdateTask(self._rembg_signals))

    def _on_rembg_update_done(self, ok: bool, what: str, info: str) -> None:
        """Итог обновления rembg: что изменилось — в статус, журнал, диалог."""
        self._rembg_busy = False
        modstatus.done("rembg")
        if ok:
            msg = tr("viewer.rembg_update_done", what=what)
            self.status.setText(msg)
            applog.event("log.event.rembg_update_done", what=what)
            QMessageBox.information(self, tr("viewer.rembg"), msg)
        else:
            msg = tr("viewer.rembg_update_fail", info=info)
            self.status.setText(msg)
            applog.error(tr("log.event.rembg_update_fail", info=info))
            QMessageBox.warning(self, tr("viewer.rembg"), msg)

    # ---------- удаление фона (rembg, v0.7.12) ----------

    def _rembg_targets(self) -> list[str]:
        """Файлы для «Удалить фон»: выделенные плитки, иначе открытая."""
        paths = self.list.selected_paths()
        if not paths:
            row = self.list.currentRow()
            if 0 <= row < len(self._paths):
                paths = [self._paths[row]]
        return paths

    def _on_rembg_button(self) -> None:
        """Кнопка/пункт меню «Удалить фон»: пачка уходит в фоновую задачу."""
        if self._rembg_busy:
            self.status.setText(tr("viewer.rembg_busy"))
            return
        targets = self._rembg_targets()
        if not targets:
            self.status.setText(tr("viewer.rembg_none"))
            return
        if not rembg_manager.is_installed():
            # модуля нет — предложить установить, не отпуская в терминал
            ans = QMessageBox.question(self, tr("viewer.rembg"),
                                       tr("viewer.rembg_inst_q"))
            if ans == QMessageBox.StandardButton.Yes:
                self._rembg_start_install(pending=targets)
            return
        self._rembg_start(targets)

    def _rembg_start(self, paths: list[str]) -> None:
        """Запустить фоновую обработку пачки (одна сессия на пачку)."""
        # новый запуск закрывает прошлый вопрос «Сохранить/Вернуть» как
        # «Сохранить»: результаты прежней пачки остаются на диске
        dlg, self._rembg_choice = self._rembg_choice, None
        if dlg is not None:
            try:
                dlg.done(_REMBG_SAVE)
            except RuntimeError:
                pass   # окно уже уничтожено вместе с вьюером
        self._rembg_results = []
        jobs: list[tuple[str, str]] = []
        skipped = 0
        for p in paths:
            out = rembg_manager.nobg_path(p)
            if out:
                jobs.append((p, out))
            else:
                skipped += 1   # это уже результат — повторять бессмысленно
        if skipped:
            applog.event("log.event.rembg_skip", n=skipped)
        if not jobs:
            self.status.setText(tr("viewer.rembg_already"))
            return
        self._rembg_busy = True
        self._rembg_total = len(jobs)
        self._rembg_ok = 0
        self._rembg_fail = 0
        self._rembg_t0 = time.perf_counter()
        # процесс модуля — на постоянном месте статус-бара (v0.8.20);
        # в подписи вьюера тот же текст НЕ дублируется (v0.8.21)
        modstatus.report("rembg", tr("viewer.rembg_progress", done=0,
                                     n=len(jobs),
                                     name=os.path.basename(jobs[0][0])),
                         frac=0.0)
        applog.event("log.event.rembg_start", n=len(jobs),
                     model=self._rembg_model)
        # чтение файлов — в самой задаче, GUI не ждёт; на сетевом диске —
        # узкий отдельный пул, чтобы подвисший сервер не занял всех
        # потоков миниатюр (принцип v0.7.2)
        pool = (self._net_pool
                if any(_is_remote_path(p) for p, _out in jobs)
                else QThreadPool.globalInstance())
        pool.start(rembg_manager.RemoveBgTask(jobs, self._rembg_model,
                                              self._rembg_signals))

    def _on_rembg_file_start(self, path: str, idx: int) -> None:
        """Начался файл пачки: строка статуса оживает до file_done (v0.8.20)."""
        modstatus.report("rembg", tr("viewer.rembg_progress", done=idx - 1,
                                     n=self._rembg_total,
                                     name=os.path.basename(path)),
                         frac=(idx - 1) / max(1, self._rembg_total))

    def _on_rembg_file_done(self, path: str, out: str, ok: bool, err: str) -> None:
        """Промежуточный итог по файлу: прогресс в статусе, ошибки в журнал."""
        if ok:
            self._rembg_ok += 1
            self._rembg_results.append(out)   # результат этой пачки — для выбора
        else:
            self._rembg_fail += 1
            applog.error(tr("log.event.rembg_file_err",
                            name=os.path.basename(path), err=err))
        done = self._rembg_ok + self._rembg_fail
        modstatus.report("rembg", tr("viewer.rembg_progress", done=done,
                                     n=self._rembg_total,
                                     name=os.path.basename(path)),
                         frac=done / max(1, self._rembg_total))

    def _on_rembg_batch_done(self, ok: int, fail: int) -> None:
        self._rembg_busy = False
        modstatus.done("rembg")   # активность снята; итог — в статусе и журнале
        ms = round((time.perf_counter() - self._rembg_t0) * 1000)
        tail = tr("viewer.rembg_done_fail", fail=fail) if fail else ""
        self.status.setText(tr("viewer.rembg_done", ok=ok) + tail)
        applog.event("log.event.rembg_done", ok=ok, fail=fail,
                     ms=ms, extra=applog.extra(model=self._rembg_model))
        if ok:
            self.refresh()   # файлы «_nobg.png» появляются в ленте
            self._open_rembg_choice()   # сохранить результат или вернуть оригиналы

    # ---------- выбор после удаления фона: сохранить или вернуть (v0.7.15) ----------

    def _open_rembg_choice(self) -> None:
        """Спросить после пачки: сохранить результат или вернуть оригиналы.

        Диалог немодальный — пока он открыт, лента кликается, и результат
        можно рассмотреть в полном размере. Превью строится только для
        локальных файлов: чтение по сети в GUI-потоке запрещено (v0.7.2)."""
        results = list(self._rembg_results)
        if not results:
            return
        preview = (None if _is_remote_path(results[0])
                   else _checker_pixmap(results[0]))
        dlg = _RembgChoiceDialog(self, results, preview)
        dlg.finished.connect(self._on_rembg_choice_done)
        dlg.finished.connect(dlg.deleteLater)   # закрытый диалог — уничтожить
        self._rembg_choice = dlg
        dlg.show()

    def _on_rembg_choice_done(self, code: int) -> None:
        """Диалог выбора закрыт: сохранить результат или вернуть оригиналы.

        Любое закрытие, кроме явного «Вернуть оригиналы» (кнопка), — это
        «Сохранить»: результат теряется только по осознанному клику."""
        results, self._rembg_results = self._rembg_results, []
        self._rembg_choice = None
        if code == _REMBG_REVERT and results:
            self.status.setText(tr("viewer.rembg_reverting"))
            applog.event("log.event.rembg_revert_start", n=len(results))
            QThreadPool.globalInstance().start(
                rembg_manager.RevertTask(results, self._rembg_signals))
        elif results:
            applog.event("log.event.rembg_saved", n=len(results))
            self.status.setText(tr("viewer.rembg_saved", n=len(results)))

    def _on_rembg_revert_done(self, removed: list, errors: list) -> None:
        """Результаты убраны: лента без «_nobg», статус и журнал в курсе.

        Оригиналы не трогались, так что «вернуть» — это просто убрать
        файлы-результаты этой пачки; порядок в ленте чинится как после
        обычного удаления (v0.7.11)."""
        for p in removed:
            self._remove_row_by_path(p)
        if removed:
            # строки сместились — кэш миниатюр по номерам строк больше не верен
            self._list_rows_changed()
        for p, err in errors:
            applog.error(tr("log.event.rembg_revert_err",
                            name=os.path.basename(p), err=err))
        applog.event("log.event.rembg_revert", n=len(removed),
                     fail=len(errors))
        if errors:
            self.status.setText(tr("viewer.rembg_revert_fail",
                                   ok=len(removed), fail=len(errors)))
        else:
            self.status.setText(tr("viewer.rembg_reverted", n=len(removed)))

    # ---------- статусная строка рассказывает про модель (v0.7.15) ----------

    def _on_rembg_model_prepare(self, model: str) -> None:
        """Модель готовится: грузится в память, при отсутствии качается."""
        modstatus.report("rembg", tr("viewer.rembg_prepare", model=model),
                         frac=-1.0)

    def _on_rembg_model_ready(self, model: str) -> None:
        """Модель готова — дальше идут уже сообщения обработки файлов."""
        modstatus.report("rembg", tr("viewer.rembg_ready", model=model),
                         frac=-1.0)

    def _on_rembg_model_dl_start(self, model: str, total: int) -> None:
        """Началось скачивание модели — имя запоминаем для тиков прогресса."""
        self._dl_model = model
        if total > 0:
            modstatus.report("rembg", tr("viewer.rembg_dl_prog", model=model,
                                         done=_fmt_bytes(0),
                                         total=_fmt_bytes(total), pct=0),
                             frac=0.0)
        else:
            modstatus.report("rembg", tr("viewer.rembg_dl_start", model=model),
                             frac=-1.0)

    def _on_rembg_model_dl_progress(self, done: int, total: int) -> None:
        """Тик скачивания: только виджет модулей, журнал не заваливаем."""
        if total > 0:
            pct = round(done * 100 / total)
            text = tr("viewer.rembg_dl_prog", model=self._dl_model,
                      done=_fmt_bytes(done), total=_fmt_bytes(total), pct=pct)
            modstatus.report("rembg", text, frac=done / total)
        else:
            text = tr("viewer.rembg_dl_prog_na", model=self._dl_model,
                      done=_fmt_bytes(done))
            modstatus.report("rembg", text, frac=-1.0)

    def _on_rembg_model_dl_done(self, model: str, size: int, ms: int) -> None:
        """Модель скачана: строка в журнал и итог в статусной строке."""
        applog.event("log.event.rembg_model_dl", model=model,
                     size=_fmt_bytes(size), ms=ms)
        self.status.setText(tr("viewer.rembg_dl_done", model=model,
                               size=_fmt_bytes(size)))

    def _rembg_start_install(self, pending: list[str] | None = None) -> None:
        """Установить rembg в фоне; ``pending`` — что обработать после."""
        if self._rembg_busy:
            self.status.setText(tr("viewer.rembg_busy"))
            return
        self._rembg_busy = True
        self._rembg_pending = list(pending or [])
        modstatus.report("rembg", tr("viewer.rembg_installing"), frac=-1.0)
        applog.event("log.event.rembg_install_start")
        QThreadPool.globalInstance().start(
            rembg_manager.InstallTask(self._rembg_signals))

    def _on_rembg_install_done(self, ok: bool, info: str) -> None:
        self._rembg_busy = False
        modstatus.done("rembg")
        pending, self._rembg_pending = self._rembg_pending, None
        if ok:
            applog.event("log.event.rembg_install_done")
            if pending:
                # установка была по клику «Удалить фон» — сразу продолжаем
                self._rembg_start(pending)
            else:
                self.status.setText(tr("viewer.rembg_install_ok"))
                QMessageBox.information(self, tr("viewer.rembg"),
                                        tr("viewer.rembg_install_ok"))
        else:
            self.status.setText(tr("viewer.rembg_install_fail", info=info))
            applog.error(tr("log.event.rembg_install_fail", info=info))
            QMessageBox.warning(self, tr("viewer.rembg"),
                                tr("viewer.rembg_install_fail", info=info))

    def _rembg_start_uninstall(self) -> None:
        """Удалить rembg и скачанные модели целиком (после подтверждения)."""
        if self._rembg_busy:
            self.status.setText(tr("viewer.rembg_busy"))
            return
        mb = _fmt_bytes(rembg_manager.models_size())
        ans = QMessageBox.question(self, tr("viewer.rembg"),
                                   tr("viewer.rembg_uninst_q", mb=mb))
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._rembg_busy = True
        modstatus.report("rembg", tr("viewer.rembg_uninstalling"), frac=-1.0)
        applog.event("log.event.rembg_uninstall_start")
        QThreadPool.globalInstance().start(
            rembg_manager.UninstallTask(self._rembg_signals))

    def _on_rembg_uninstall_done(self, ok: bool, info: str,
                                 freed_mb: int) -> None:
        self._rembg_busy = False
        modstatus.done("rembg")
        if ok:
            freed = _fmt_bytes(freed_mb * 1024 * 1024)
            self.status.setText(tr("viewer.rembg_uninst_ok", mb=freed))
            applog.event("log.event.rembg_uninstall_done", mb=freed_mb)
            QMessageBox.information(self, tr("viewer.rembg"),
                                    tr("viewer.rembg_uninst_ok", mb=freed))
        else:
            self.status.setText(tr("viewer.rembg_uninst_fail", info=info))
            applog.error(tr("log.event.rembg_uninstall_fail", info=info))
            QMessageBox.warning(self, tr("viewer.rembg"),
                                tr("viewer.rembg_uninst_fail", info=info))

    def _on_rembg_model(self, model_id: str) -> None:
        """Выбор модели в подменю: запоминается между запусками."""
        if model_id == self._rembg_model:
            return
        self._rembg_model = model_id
        QSettings("ImageHunter", "ImageHunter").setValue(
            rembg_manager.MODEL_KEY, model_id)
        applog.event("log.event.rembg_model", model=model_id)

    # ---------- водяные знаки: публичный доступ для меню «Модули» (v0.8.11) ----------

    def wm_is_installed(self) -> bool:
        """Установлен ли модуль (меню «Модули» строит по этому пункты)."""
        return watermark_manager.is_installed()

    def wm_is_busy(self) -> bool:
        """Идёт ли pip-установка/удаление или обработка пачки (guard меню)."""
        return self._wm_busy

    def wm_current_model(self) -> str:
        """Выбранный детектор — для галочки в меню «Модули»."""
        return self._wm_model

    def wm_install(self) -> None:
        """Установить модуль из меню «Модули» (без отложенной пачки файлов)."""
        self._wm_start_install()

    def wm_uninstall(self) -> None:
        """Удалить модуль и модели из меню «Модули» (с подтверждением)."""
        self._wm_start_uninstall()

    def wm_set_model(self, model_id: str) -> None:
        """Выбрать детектор из меню «Модули» (запоминается в настройках)."""
        self._on_wm_model(model_id)

    def wm_update(self) -> None:
        """Обновить установленный модуль из меню «Модули» (v0.8.15).

        Пакеты (iopaint/transformers/timm) сверяются с PyPI, модели —
        с Hugging Face и релизом big-lama; всё в фоне, guard тот же,
        что у установки/удаления — два pip-а одновременно не запускаются.
        """
        if self._wm_busy:
            self.status.setText(tr("viewer.wm_busy"))
            return
        if not watermark_manager.is_installed():
            return   # меню показывает пункт только у установленного модуля
        self._wm_busy = True
        modstatus.report("wm", tr("viewer.wm_updating"), frac=-1.0)
        applog.event("log.event.wm_update_start")
        QThreadPool.globalInstance().start(
            watermark_manager.UpdateTask(self._wm_signals, self._wm_model))

    def _on_wm_update_done(self, ok: bool, what: str, info: str) -> None:
        """Итог обновления модуля: что изменилось — в статус, журнал, диалог."""
        self._wm_busy = False
        modstatus.done("wm")
        if ok:
            msg = tr("viewer.wm_update_done", what=what)
            self.status.setText(msg)
            applog.event("log.event.wm_update_done", what=what)
            QMessageBox.information(self, tr("viewer.wm"), msg)
        else:
            msg = tr("viewer.wm_update_fail", info=info)
            self.status.setText(msg)
            applog.error(tr("log.event.wm_update_fail", info=info))
            QMessageBox.warning(self, tr("viewer.wm"), msg)

    # ---------- удаление водяных знаков (Florence-2 + LaMa, v0.8.11) ----------

    def _wm_targets(self) -> list[str]:
        """Файлы для «Убрать водяные знаки»: выделенные плитки, иначе открытая."""
        paths = self.list.selected_paths()
        if not paths:
            row = self.list.currentRow()
            if 0 <= row < len(self._paths):
                paths = [self._paths[row]]
        return paths

    def _on_wm_button(self) -> None:
        """Кнопка/пункт меню «Убрать водяные знаки»: пачка уходит в фон."""
        if self._wm_busy:
            self.status.setText(tr("viewer.wm_busy"))
            return
        targets = self._wm_targets()
        if not targets:
            self.status.setText(tr("viewer.wm_none"))
            return
        if not watermark_manager.is_installed():
            # модуля нет — предложить установить, не отпуская в терминал
            ans = QMessageBox.question(self, tr("viewer.wm"),
                                       tr("viewer.wm_inst_q"))
            if ans == QMessageBox.StandardButton.Yes:
                self._wm_start_install(pending=targets)
            return
        self._wm_start(targets)

    def _wm_start(self, paths: list[str]) -> None:
        """Запустить фоновую обработку пачки (модели грузятся один раз)."""
        jobs: list[tuple[str, str]] = []
        skipped = 0
        for p in paths:
            out = watermark_manager.nowm_path(p)
            if out:
                jobs.append((p, out))
            else:
                skipped += 1   # уже результат или GIF — повторять бессмысленно
        if skipped:
            applog.event("log.event.wm_skip", n=skipped)
        if not jobs:
            self.status.setText(tr("viewer.wm_already"))
            return
        self._wm_run(jobs)

    def _wm_run(self, jobs: list[tuple[str, str]],
                sel: tuple[int, int, int, int] | None = None) -> None:
        """Общий запуск конвейера (v0.8.22): пачка после автодетекции

        или одно убирание по выделению — sel (x, y, w, h) картинки.
        Счётчики, статус-виджет и пул общие: процесс убирания по
        выделению виден в строке статуса ровно как пачка (v0.8.20/21).
        """
        self._wm_busy = True
        self._wm_total = len(jobs)
        self._wm_ok = 0
        self._wm_clean = 0
        self._wm_fail = 0
        self._wm_t0 = time.perf_counter()
        # процесс модуля — на постоянном месте статус-бара (v0.8.20);
        # в подписи вьюера тот же текст НЕ дублируется (v0.8.21)
        modstatus.report("wm", tr("viewer.wm_progress", done=0, n=len(jobs),
                                  name=os.path.basename(jobs[0][0])),
                         frac=0.0)
        if sel is None:
            applog.event("log.event.wm_start", n=len(jobs), model=self._wm_model)
            task = watermark_manager.RemoveWatermarkTask(
                jobs, self._wm_model, self._wm_signals)
        else:
            applog.event("log.event.wm_sel_start", w=sel[2], h=sel[3],
                         name=os.path.basename(jobs[0][0]),
                         model=self._wm_model)
            task = watermark_manager.RemoveWatermarkTask(
                jobs, self._wm_model, self._wm_signals, sel=sel)
        # чтение файлов — в самой задаче, GUI не ждёт; на сетевом диске —
        # узкий отдельный пул, как у rembg (принцип v0.7.2)
        pool = (self._net_pool
                if any(_is_remote_path(p) for p, _out in jobs)
                else QThreadPool.globalInstance())
        pool.start(task)

    def _wm_sel_start(self) -> None:
        """«🧽 Убрать в выделении»: ватермарки в выделении обрезки (v0.8.22).

        Пожелание: «сделай возможность удалять ватермарки из выделения на
        картинке». Рамку рисует режим «✂ Обрезать» (v0.8.7): резинка,
        восемь ручек, перенос — выделение живёт в координатах картинки,
        переживает зум и совпадает с показом (у обоих EXIF-разворот).
        LaMa закрашивает ровно выделение — детекция Florence-2 не нужна
        и не грузится. Оригинал не трогается: результат — отдельный файл
        «имя_nowm.ext» (принцип модуля); чистка остатков на УЖЕ готовом
        «_nowm»-файле получает свободное «имя_nowm-1.ext» и дальше.
        После готовности результат откроется в просмотре с рамкой на
        месте — остатки можно чистить не перекликивая.
        """
        if self._wm_busy:
            self.status.setText(tr("viewer.wm_busy"))
            return
        if (not self._crop_mode or self._pixmap is None
                or not self.view_label.has_selection()):
            return
        if not watermark_manager.is_installed():
            # модуля нет — предложить установить, не отпуская в терминал,
            # после установки продолжить ровно это выделение
            ans = QMessageBox.question(self, tr("viewer.wm"),
                                       tr("viewer.wm_inst_q"))
            if ans == QMessageBox.StandardButton.Yes:
                self._wm_sel_pending = True
                self._wm_start_install()
            return
        row = self.list.currentRow()
        src = self._paths[row] if 0 <= row < len(self._paths) else ""
        out = watermark_manager.sel_result_path(src) if src else ""
        if not out:
            # GIF/без расширения в режим обрезки не попадают — защита честная
            self.status.setText(tr("viewer.wm_already"))
            return
        sel = self.view_label.selection()
        self._wm_sel_open = out   # откроется после пересканирования (_on_wm_batch_done)
        self._wm_run([(src, out)],
                     sel=(sel.x(), sel.y(), sel.width(), sel.height()))

    def _on_wm_file_start(self, path: str, idx: int) -> None:
        """Начался файл пачки: строка статуса оживает до file_done (v0.8.20)."""
        self._wm_idx = idx
        modstatus.report("wm", tr("viewer.wm_progress", done=idx - 1,
                                  n=self._wm_total,
                                  name=os.path.basename(path)),
                         frac=(idx - 1) / max(1, self._wm_total))

    def _on_wm_phase(self, path: str, code: str, extra: int) -> None:
        """Фаза внутри файла — детекция/закраска/сохранение (v0.8.20).

        Пожелание: «видеть в строке статуса процесс и/или статус работы
        модулей, особенно модуля удаления ватермарков». Конвейер на одной
        большой картинке идёт десятки секунд: без фаз прогресс замирал
        на «N/M», и было не понять, что происходит и жив ли процесс.
        Веса фаз двигают полосу внутри файла: детекция ~10 %, закраска —
        до ~50 %, сохранение — до ~90 %.
        """
        if code == "detect":
            phase, weight = tr("viewer.wm_phase_detect"), 0.1
        elif code == "found":
            phase, weight = tr("viewer.wm_phase_found", n=extra), 0.5
        elif code == "inpaint":
            phase, weight = tr("viewer.wm_phase_inpaint"), 0.5
        else:   # "save"
            phase, weight = tr("viewer.wm_phase_save"), 0.9
        idx = self._wm_idx
        modstatus.report(
            "wm",
            tr("viewer.wm_phase", done=idx - 1, n=self._wm_total,
               name=os.path.basename(path), phase=phase),
            frac=(idx - 1 + weight) / max(1, self._wm_total))

    def _on_wm_model_dl_start(self, model: str, total: int) -> None:
        """Началось скачивание модели модуля (LaMa/Florence-2, v0.8.20)."""
        self._wm_dl_model = model
        if total > 0:
            modstatus.report("wm", tr("viewer.wm_dl_prog", model=model,
                                      done=_fmt_bytes(0),
                                      total=_fmt_bytes(total), pct=0),
                             frac=0.0)
        else:
            modstatus.report("wm", tr("viewer.wm_dl_start", model=model),
                             frac=-1.0)

    def _on_wm_model_dl_progress(self, done: int, total: int) -> None:
        """Тик скачивания модели: полоса и мегабайты в статус-виджете."""
        model = self._wm_dl_model
        if total > 0:
            modstatus.report("wm", tr("viewer.wm_dl_prog", model=model,
                                      done=_fmt_bytes(done),
                                      total=_fmt_bytes(total),
                                      pct=round(done * 100 / total)),
                             frac=done / total)
        else:
            modstatus.report("wm", tr("viewer.wm_dl_prog_na", model=model,
                                      done=_fmt_bytes(done)), frac=-1.0)

    def _on_wm_file_done(self, path: str, out: str, ok: bool, err: str) -> None:
        """Промежуточный итог по файлу: прогресс в статусе, ошибки в журнал."""
        if ok:
            if out:
                self._wm_ok += 1
            else:
                self._wm_clean += 1   # водяных знаков не нашлось — файл чист
        else:
            self._wm_fail += 1
            applog.error(tr("log.event.wm_file_err",
                            name=os.path.basename(path), err=err))
        done = self._wm_ok + self._wm_clean + self._wm_fail
        modstatus.report("wm", tr("viewer.wm_progress", done=done,
                                  n=self._wm_total,
                                  name=os.path.basename(path)),
                         frac=done / max(1, self._wm_total))

    def _on_wm_batch_done(self, ok: int, fail: int) -> None:
        self._wm_busy = False
        modstatus.done("wm")   # активность снята; итог — в статусе и журнале
        ms = round((time.perf_counter() - self._wm_t0) * 1000)
        msg = tr("viewer.wm_done", ok=ok)
        if self._wm_clean:
            msg += tr("viewer.wm_clean", clean=self._wm_clean)
        if fail:
            msg += tr("viewer.wm_done_fail", fail=fail)
        self.status.setText(msg)
        applog.event("log.event.wm_done", ok=ok, clean=self._wm_clean,
                     fail=fail, ms=ms)
        open_path, self._wm_sel_open = self._wm_sel_open, ""
        if ok:
            self.refresh()   # файлы «*_nowm» появляются в ленте
            if open_path:
                # убирание по выделению (v0.8.22): результат откроется после
                # пересканирования, режим обрезки встанет на него сам —
                # остатки знака чистятся той же рамкой без перекликивания
                self._select_after_scan = open_path
                self._crop_continue = True
        # open_path при неуспехе честно сброшен: результата нет — открывать нечего

    def _on_wm_model_prepare(self, model: str) -> None:
        """Модели готовятся: грузятся в память, при первом запуске качаются."""
        modstatus.report("wm", tr("viewer.wm_prepare", model=model),
                         frac=-1.0)

    def _on_wm_model_ready(self, model: str) -> None:
        """Модели готовы — дальше идут уже сообщения обработки файлов."""
        modstatus.report("wm", tr("viewer.wm_ready", model=model),
                         frac=-1.0)

    def _wm_start_install(self, pending: list[str] | None = None) -> None:
        """Установить модуль в фоне; ``pending`` — что обработать после."""
        if self._wm_busy:
            self.status.setText(tr("viewer.wm_busy"))
            return
        self._wm_busy = True
        self._wm_pending = list(pending or [])
        modstatus.report("wm", tr("viewer.wm_installing"), frac=-1.0)
        applog.event("log.event.wm_install_start")
        QThreadPool.globalInstance().start(
            watermark_manager.InstallTask(self._wm_signals))

    def _on_wm_install_done(self, ok: bool, info: str) -> None:
        self._wm_busy = False
        modstatus.done("wm")
        pending, self._wm_pending = self._wm_pending, None
        sel_pending, self._wm_sel_pending = self._wm_sel_pending, False
        if ok:
            applog.event("log.event.wm_install_done")
            if pending:
                # установка была по клику «Убрать водяные знаки» — продолжаем
                self._wm_start(pending)
            elif sel_pending:
                # установка была по клику «🧽 Убрать в выделении» (v0.8.22)
                # — продолжаем то же выделение
                self._wm_sel_start()
            else:
                self.status.setText(tr("viewer.wm_install_ok"))
                QMessageBox.information(self, tr("viewer.wm"),
                                        tr("viewer.wm_install_ok"))
        else:
            self.status.setText(tr("viewer.wm_install_fail", info=info))
            applog.error(tr("log.event.wm_install_fail", info=info))
            QMessageBox.warning(self, tr("viewer.wm"),
                                tr("viewer.wm_install_fail", info=info))

    def _wm_start_uninstall(self) -> None:
        """Удалить модуль и скачанные модели целиком (после подтверждения)."""
        if self._wm_busy:
            self.status.setText(tr("viewer.wm_busy"))
            return
        mb = _fmt_bytes(watermark_manager.models_size())
        ans = QMessageBox.question(self, tr("viewer.wm"),
                                   tr("viewer.wm_uninst_q", mb=mb))
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._wm_busy = True
        modstatus.report("wm", tr("viewer.wm_uninstalling"), frac=-1.0)
        applog.event("log.event.wm_uninstall_start")
        QThreadPool.globalInstance().start(
            watermark_manager.UninstallTask(self._wm_signals))

    def _on_wm_uninstall_done(self, ok: bool, info: str,
                              freed_mb: int) -> None:
        self._wm_busy = False
        modstatus.done("wm")
        if ok:
            freed = _fmt_bytes(freed_mb * 1024 * 1024)
            self.status.setText(tr("viewer.wm_uninst_ok", mb=freed))
            applog.event("log.event.wm_uninstall_done", mb=freed_mb)
            QMessageBox.information(self, tr("viewer.wm"),
                                    tr("viewer.wm_uninst_ok", mb=freed))
        else:
            self.status.setText(tr("viewer.wm_uninst_fail", info=info))
            applog.error(tr("log.event.wm_uninstall_fail", info=info))
            QMessageBox.warning(self, tr("viewer.wm"),
                                tr("viewer.wm_uninst_fail", info=info))

    def _on_wm_model(self, model_id: str) -> None:
        """Выбор детектора в подменю: запоминается между запусками."""
        if model_id == self._wm_model:
            return
        self._wm_model = model_id
        QSettings("ImageHunter", "ImageHunter").setValue(
            watermark_manager.MODEL_KEY, model_id)
        applog.event("log.event.wm_model", model=model_id)

    # ---------- улучшение качества: публичный доступ для меню «Модули» (v0.8.24) ----------

    def ups_is_installed(self) -> bool:
        """Установлен ли модуль (меню «Модули» строит по этому пункты)."""
        return upscale_manager.is_installed()

    def ups_is_busy(self) -> bool:
        """Идёт ли pip-установка/удаление или обработка пачки (guard меню)."""
        return self._ups_busy

    def ups_current_model(self) -> str:
        """Выбранные веса — для галочки в меню «Модули»."""
        return self._ups_model

    def ups_install(self) -> None:
        """Установить модуль из меню «Модули» (без отложенной пачки файлов)."""
        self._ups_start_install()

    def ups_uninstall(self) -> None:
        """Удалить модуль и скачанные веса из меню «Модули» (с подтверждением)."""
        self._ups_start_uninstall()

    def ups_set_model(self, model_id: str) -> None:
        """Выбрать модель из меню «Модули» (запоминается в настройках)."""
        self._on_up_model(model_id)

    def ups_update(self) -> None:
        """Обновить установленный модуль из меню «Модули» (v0.8.24).

        Веса выбранной модели сверяются с релизом GitHub (torch не
        перекладывается — общее достояние с модулем водяных знаков);
        guard тот же, что у установки/удаления — два действия одновременно
        не запускаются.
        """
        if self._ups_busy:
            self.status.setText(tr("viewer.up_busy"))
            return
        if not upscale_manager.is_installed():
            return   # меню показывает пункт только у установленного модуля
        self._ups_busy = True
        modstatus.report("up", tr("viewer.up_updating"), frac=-1.0)
        applog.event("log.event.up_update_start")
        QThreadPool.globalInstance().start(
            upscale_manager.UpdateTask(self._ups_signals, self._ups_model))

    def _on_up_update_done(self, ok: bool, what: str, info: str) -> None:
        """Итог обновления модуля: что изменилось — в статус, журнал, диалог."""
        self._ups_busy = False
        modstatus.done("up")
        if ok:
            msg = tr("viewer.up_update_done", what=what)
            self.status.setText(msg)
            applog.event("log.event.up_update_done", what=what)
            QMessageBox.information(self, tr("viewer.up"), msg)
        else:
            msg = tr("viewer.up_update_fail", info=info)
            self.status.setText(msg)
            applog.error(tr("log.event.up_update_fail", info=info))
            QMessageBox.warning(self, tr("viewer.up"), msg)

    # ---------- улучшение качества (Real-ESRGAN, v0.8.24) ----------

    def _ups_targets(self) -> list[str]:
        """Файлы для «Улучшить»: выделенные плитки, иначе открытая."""
        paths = self.list.selected_paths()
        if not paths:
            row = self.list.currentRow()
            if 0 <= row < len(self._paths):
                paths = [self._paths[row]]
        return paths

    def _on_up_button(self) -> None:
        """Кнопка/пункт меню «Улучшить»: пачка уходит в фоновую задачу."""
        if self._ups_busy:
            self.status.setText(tr("viewer.up_busy"))
            return
        targets = self._ups_targets()
        if not targets:
            self.status.setText(tr("viewer.up_none"))
            return
        if not upscale_manager.is_installed():
            # модуля нет — предложить установить, не отпуская в терминал
            ans = QMessageBox.question(self, tr("viewer.up"),
                                       tr("viewer.up_inst_q"))
            if ans == QMessageBox.StandardButton.Yes:
                self._ups_start_install(pending=targets)
            return
        self._ups_start(targets)

    def _ups_start(self, paths: list[str]) -> None:
        """Запустить фоновую обработку пачки (модель грузится один раз)."""
        # новый запуск закрывает прошлый вопрос «Сохранить/Вернуть» как
        # «Сохранить»: результаты прежней пачки остаются на диске
        dlg, self._ups_choice = self._ups_choice, None
        if dlg is not None:
            try:
                dlg.done(_REMBG_SAVE)
            except RuntimeError:
                pass   # окно уже уничтожено вместе с вьюером
        self._ups_results = []
        scale = upscale_manager.model_scale(self._ups_model)
        jobs: list[tuple[str, str]] = []
        skipped = 0
        for p in paths:
            out = upscale_manager.up_path(p, scale)
            if out:
                jobs.append((p, out))
            else:
                skipped += 1   # GIF/без расширения/уже результат
        if skipped:
            applog.event("log.event.up_skip", n=skipped)
        if not jobs:
            self.status.setText(tr("viewer.up_already"))
            return
        self._ups_busy = True
        self._ups_total = len(jobs)
        self._ups_ok = 0
        self._ups_fail = 0
        self._ups_t0 = time.perf_counter()
        # процесс модуля — на постоянном месте статус-бара (v0.8.20);
        # в подписи вьюера тот же текст НЕ дублируется (v0.8.21)
        modstatus.report("up", tr("viewer.up_progress", done=0, n=len(jobs),
                                  name=os.path.basename(jobs[0][0])),
                         frac=0.0)
        applog.event("log.event.up_start", n=len(jobs),
                     model=self._ups_model)
        # чтение файлов — в самой задаче, GUI не ждёт; на сетевом диске —
        # узкий отдельный пул, чтобы подвисший сервер не занял всех
        # потоков миниатюр (принцип v0.7.2)
        pool = (self._net_pool
                if any(_is_remote_path(p) for p, _out in jobs)
                else QThreadPool.globalInstance())
        pool.start(upscale_manager.UpscaleTask(jobs, self._ups_model,
                                               self._ups_signals))

    def _on_up_file_start(self, path: str, idx: int) -> None:
        """Начался файл пачки: строка статуса оживает до file_done (v0.8.20)."""
        self._ups_idx = idx
        modstatus.report("up", tr("viewer.up_progress", done=idx - 1,
                                  n=self._ups_total,
                                  name=os.path.basename(path)),
                         frac=(idx - 1) / max(1, self._ups_total))

    def _on_up_phase(self, path: str, code: str, cur: int, total: int) -> None:
        """Плитки внутри файла: Real-ESRGAN на большой картинке идёт долго,
        без фаз прогресс замирал на «N/M» до завершения файла."""
        phase = tr("viewer.up_phase_tile", cur=cur, total=total)
        frac = ((self._ups_idx - 1) + min(cur / max(1, total), 0.95)) \
            / max(1, self._ups_total)
        modstatus.report(
            "up",
            tr("viewer.up_phase", done=self._ups_idx - 1, n=self._ups_total,
               name=os.path.basename(path), phase=phase),
            frac=frac)
        if cur in _tile_log_points(total):
            # журнал молчал все 11 минут улучшения (репорт v0.8.25) —
            # ключевые плитки пишем и туда: начало, четверти, последняя
            applog.event("log.event.up_tile",
                         name=os.path.basename(path), cur=cur, total=total)

    def _on_up_file_done(self, path: str, out: str, ok: bool, err: str) -> None:
        """Промежуточный итог по файлу: прогресс в статусе, ошибки в журнал."""
        if ok:
            self._ups_ok += 1
            self._ups_results.append(out)   # результат этой пачки — для выбора
        else:
            self._ups_fail += 1
            applog.error(tr("log.event.up_file_err",
                            name=os.path.basename(path), err=err))
        done = self._ups_ok + self._ups_fail
        modstatus.report("up", tr("viewer.up_progress", done=done,
                                  n=self._ups_total,
                                  name=os.path.basename(path)),
                         frac=done / max(1, self._ups_total))

    def _on_up_batch_done(self, ok: int, fail: int) -> None:
        self._ups_busy = False
        modstatus.done("up")   # активность снята; итог — в статусе и журнале
        ms = round((time.perf_counter() - self._ups_t0) * 1000)
        tail = tr("viewer.up_done_fail", fail=fail) if fail else ""
        self.status.setText(tr("viewer.up_done", ok=ok) + tail)
        applog.event("log.event.up_done", ok=ok, fail=fail, ms=ms,
                     extra=applog.extra(model=self._ups_model))
        if ok:
            self.refresh()   # файлы «_x4/_x2» появляются в ленте
            self._open_up_choice()   # сохранить результат или вернуть оригиналы

    # ---------- выбор после улучшения: сохранить или вернуть (v0.8.24) ----------

    def _open_up_choice(self) -> None:
        """Спросить после пачки: сохранить результат или вернуть оригиналы.

        Тот же немодальный диалог, что у удаления фона: пока окно открыто,
        лента кликается, и результат можно рассмотреть в полном размере."""
        results = list(self._ups_results)
        if not results:
            return
        preview = (None if _is_remote_path(results[0])
                   else _checker_pixmap(results[0]))
        dlg = _RembgChoiceDialog(self, results, preview,
                                 title_key="viewer.up",
                                 q_key="viewer.up_choice_q",
                                 more_key="viewer.up_choice_more",
                                 revert_key="viewer.up_btn_revert",
                                 revert_tip_key="viewer.up_btn_revert_tip",
                                 save_key="viewer.up_btn_save",
                                 save_tip_key="viewer.up_btn_save_tip")
        dlg.finished.connect(self._on_up_choice_done)
        dlg.finished.connect(dlg.deleteLater)   # закрытый диалог — уничтожить
        self._ups_choice = dlg
        dlg.show()

    def _on_up_choice_done(self, code: int) -> None:
        """Диалог выбора закрыт: сохранить результат или вернуть оригиналы.

        Любое закрытие, кроме явного «Вернуть оригиналы» (кнопка), — это
        «Сохранить»: результат теряется только по осознанному клику."""
        results, self._ups_results = self._ups_results, []
        self._ups_choice = None
        if code == _REMBG_REVERT and results:
            self.status.setText(tr("viewer.up_reverting"))
            applog.event("log.event.up_revert_start", n=len(results))
            QThreadPool.globalInstance().start(
                upscale_manager.RevertTask(results, self._ups_signals))
        elif results:
            applog.event("log.event.up_saved", n=len(results))
            self.status.setText(tr("viewer.up_saved", n=len(results)))

    def _on_up_revert_done(self, removed: list, errors: list) -> None:
        """Результаты убраны: лента без «_x4/_x2», статус и журнал в курсе.

        Оригиналы не трогались, так что «вернуть» — это просто убрать
        файлы-результаты этой пачки; порядок в ленте чинится как после
        обычного удаления (v0.7.11)."""
        for p in removed:
            self._remove_row_by_path(p)
        if removed:
            # строки сместились — кэш миниатюр по номерам строк больше не верен
            self._list_rows_changed()
        for p, err in errors:
            applog.error(tr("log.event.up_revert_err",
                            name=os.path.basename(p), err=err))
        applog.event("log.event.up_revert", n=len(removed), fail=len(errors))
        if errors:
            self.status.setText(tr("viewer.up_revert_fail",
                                   ok=len(removed), fail=len(errors)))
        else:
            self.status.setText(tr("viewer.up_reverted", n=len(removed)))

    # ---------- статусная строка рассказывает про модель (v0.8.24) ----------

    def _on_up_model_prepare(self, model: str) -> None:
        """Веса готовятся: грузятся в память, при отсутствии качаются."""
        modstatus.report("up", tr("viewer.up_prepare", model=model),
                         frac=-1.0)

    def _on_up_model_ready(self, model: str) -> None:
        """Веса готовы — дальше идут уже сообщения обработки файлов."""
        modstatus.report("up", tr("viewer.up_ready", model=model),
                         frac=-1.0)

    def _on_up_model_dl_start(self, model: str, total: int) -> None:
        """Началось скачивание весов — имя запоминаем для тиков прогресса."""
        self._ups_dl_model = model
        if total > 0:
            modstatus.report("up", tr("viewer.up_dl_prog", model=model,
                                      done=_fmt_bytes(0),
                                      total=_fmt_bytes(total), pct=0),
                             frac=0.0)
        else:
            modstatus.report("up", tr("viewer.up_dl_start", model=model),
                             frac=-1.0)

    def _on_up_model_dl_progress(self, done: int, total: int) -> None:
        """Тик скачивания: только виджет модулей, журнал не заваливаем."""
        if total > 0:
            pct = round(done * 100 / total)
            text = tr("viewer.up_dl_prog", model=self._ups_dl_model,
                      done=_fmt_bytes(done), total=_fmt_bytes(total), pct=pct)
            modstatus.report("up", text, frac=done / total)
        else:
            text = tr("viewer.up_dl_prog_na", model=self._ups_dl_model,
                      done=_fmt_bytes(done))
            modstatus.report("up", text, frac=-1.0)

    def _on_up_model_dl_done(self, model: str, size: int, ms: int) -> None:
        """Веса скачаны: строка в журнал и итог в статусной строке."""
        applog.event("log.event.up_model_dl", model=model,
                     size=_fmt_bytes(size), ms=ms)
        self.status.setText(tr("viewer.up_dl_done", model=model,
                               size=_fmt_bytes(size)))

    def _ups_start_install(self, pending: list[str] | None = None) -> None:
        """Установить модуль в фоне; ``pending`` — что обработать после."""
        if self._ups_busy:
            self.status.setText(tr("viewer.up_busy"))
            return
        self._ups_busy = True
        self._ups_pending = list(pending or [])
        modstatus.report("up", tr("viewer.up_installing"), frac=-1.0)
        applog.event("log.event.up_install_start")
        QThreadPool.globalInstance().start(
            upscale_manager.InstallTask(self._ups_signals))

    def _on_up_install_done(self, ok: bool, info: str) -> None:
        self._ups_busy = False
        modstatus.done("up")
        pending, self._ups_pending = self._ups_pending, None
        if ok:
            applog.event("log.event.up_install_done")
            if pending:
                # установка была по клику «Улучшить» — сразу продолжаем
                self._ups_start(pending)
            else:
                self.status.setText(tr("viewer.up_install_ok"))
                QMessageBox.information(self, tr("viewer.up"),
                                        tr("viewer.up_install_ok"))
        else:
            self.status.setText(tr("viewer.up_install_fail", info=info))
            applog.error(tr("log.event.up_install_fail", info=info))
            QMessageBox.warning(self, tr("viewer.up"),
                                tr("viewer.up_install_fail", info=info))

    def _ups_start_uninstall(self) -> None:
        """Удалить модуль и скачанные веса целиком (после подтверждения)."""
        if self._ups_busy:
            self.status.setText(tr("viewer.up_busy"))
            return
        mb = _fmt_bytes(upscale_manager.models_size())
        ans = QMessageBox.question(self, tr("viewer.up"),
                                   tr("viewer.up_uninst_q", mb=mb))
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._ups_busy = True
        modstatus.report("up", tr("viewer.up_uninstalling"), frac=-1.0)
        applog.event("log.event.up_uninstall_start")
        QThreadPool.globalInstance().start(
            upscale_manager.UninstallTask(self._ups_signals))

    def _on_up_uninstall_done(self, ok: bool, info: str,
                              freed_mb: int) -> None:
        self._ups_busy = False
        modstatus.done("up")
        if ok:
            freed = _fmt_bytes(freed_mb * 1024 * 1024)
            self.status.setText(tr("viewer.up_uninst_ok", mb=freed))
            applog.event("log.event.up_uninstall_done", mb=freed_mb)
            QMessageBox.information(self, tr("viewer.up"),
                                    tr("viewer.up_uninst_ok", mb=freed))
        else:
            self.status.setText(tr("viewer.up_uninst_fail", info=info))
            applog.error(tr("log.event.up_uninstall_fail", info=info))
            QMessageBox.warning(self, tr("viewer.up"),
                                tr("viewer.up_uninst_fail", info=info))

    def _on_up_model(self, model_id: str) -> None:
        """Выбор модели в подменю: запоминается между запусками."""
        if model_id == self._ups_model:
            return
        self._ups_model = model_id
        QSettings("ImageHunter", "ImageHunter").setValue(
            upscale_manager.MODEL_KEY, model_id)
        applog.event("log.event.up_model", model=model_id)

    def load_folder(self, folder: str, entries: list[tuple[str, int, float]] | None = None,
                    sync_tree: bool = False) -> None:
        """Открыть папку (или показать готовые entries, например из поиска).

        Когда entries не переданы, папку сканирует рабочий поток
        (_ScanTask): os.scandir по сети может занять секунды, а на подвисшем
        сервере — сетевой тайм-аут целиком; GUI-поток не ждёт — лента на это
        время очищается, статус показывает «Читаю папку…» (v0.7.2)."""
        self._cancel_search()
        # та же папка или другая? при пересканировании той же папки (refresh
        # после сохранения) серия «✂▶ К следующему» должна выжить (v0.8.7)
        same_folder = (os.path.normpath(folder) == os.path.normpath(self._folder)
                       if self._folder else False)
        self._folder = folder
        self._update_fav_button()   # ☆/★ под текущую папку
        self._gen += 1
        # не начатые задачи прошлой папки больше не нужны
        self._pool.clear()
        self._net_pool.clear()
        self._paths = []
        self._meta = []
        self.list.clear()
        self._pending_thumbs.clear()
        self._pending_dims.clear()
        self._thumb_queued.clear()
        self._thumb_done_rows.clear()
        self._thumbs_done = 0
        self._pixmap = None
        self._movie = None
        self._select_after_scan = ""   # отложенный выбор — только для своей папки
        self.set_resize_mode(False)          # смена папки закрывает ресайс (v0.8.6)
        self._update_resize_button()         # на время чтения кнопка погашена
        self.set_crop_mode(False)            # и обрезку тоже (v0.8.7)
        self.set_picker_mode(False)          # и пипетку (v0.8.8)
        self._picker_img = None              # источник цвета прошлой папки больше не нужен
        self._fill_prev_pixmap = None        # и черновик закрашивания тоже
        if not same_folder:
            self._crop_continue = False      # серия «к следующему» не переживает СМЕНУ папки
        self._update_crop_button()
        self._update_picker_button()
        if entries is None:
            self._scan_restore = False
            self._scan_sync_tree = sync_tree
            self.status.setText(tr("viewer.folder_reading"))
            # скан по сети — через узкий пул (v0.8.19): не делит слоты davfs2
            # с миниатюрами и не множит параллельные запросы к серверу
            self._io_pool(folder).start(
                _ScanTask(folder, self._gen, self._scan_signals))
            return
        self._fill_folder(folder, entries, sync_tree)

    def _fill_folder(self, folder: str, entries: list[tuple[str, int, float]],
                     sync_tree: bool) -> None:
        """Построить ленту миниатюр из готового списка файлов (GUI-поток)."""
        # таймер вокруг построения ленты: по журналу видно, что именно долго
        with applog.timed(tr("perf.op.load_folder")) as t:
            self._paths = [p for p, _s, _m in entries]
            self._meta = [(s, m) for _p, s, m in entries]
            applog.event("log.event.folder", folder=folder, n=len(self._paths))
            placeholder = QPixmap(THUMB, THUMB)
            placeholder.fill(Qt.darkGray)

            # строим только список; миниатюры грузятся ЛЕНИВО — для видимых строк
            # (см. _queue_visible_thumbs). Вход в сетевую папку с тысячами файлов
            # больше не запускает чтение всех файлов подряд.
            for row, (path, _size, _mtime) in enumerate(entries):
                item = QListWidgetItem(QIcon(placeholder), os.path.basename(path))
                item.setData(Qt.UserRole, path)
                item.setToolTip(os.path.basename(path))
                self.list.addItem(item)

            if self._paths:
                # отложенный выбор (v0.8.6): после сохранения копии нового
                # размера лента обновится и откроет именно её, а не первую плитку
                row0 = 0
                if self._select_after_scan:
                    try:
                        row0 = self._paths.index(self._select_after_scan)
                    except ValueError:
                        row0 = 0
                    self._select_after_scan = ""
                self.list.setCurrentRow(row0)
            else:
                self._select_after_scan = ""
                self._view_text(tr("viewer.no_images"))
                self.status.setText(folder or "—")
            self._schedule_visible_thumbs()

            QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", folder)
            if sync_tree:
                self._sync_tree(folder)
            t.set(files=len(self._paths))

    def _on_scan_done(self, gen: int, folder: str,
                      entries: list[tuple[str, int, float]]) -> None:
        """Скан папки завершён в фоне — построить ленту, если папка ещё актуальна."""
        if gen != self._gen or folder != self._folder:
            return                       # пока сканировали, выбрали другую папку
        if self._scan_restore and not (0 < len(entries) <= _RESTORE_MAX_FILES):
            self._scan_restore = False   # автопоказ: пустая/гигантская — молча пропускаем
            return
        self._scan_restore = False
        self._fill_folder(folder, entries, self._scan_sync_tree)
        self._scan_sync_tree = False

    # ---------- поиск по имени (без wildcard: подстрока, регистр не важен) ----------

    def _on_search_text_changed(self, text: str) -> None:
        if not text.strip():
            self._cancel_search()
            if self._folder:
                self.load_folder(self._folder)
            return
        self._search_timer.start()   # дебаунс: не ищем на каждое нажатие

    def _cancel_search(self) -> None:
        self._search_timer.stop()
        if self._search_handle is not None:
            self._search_handle.cancelled = True
            self._search_handle = None

    def _start_search_now(self) -> None:
        self._search_timer.stop()
        needle = self.search_edit.text().strip()
        if not needle:
            return
        base = self._folder
        if not base:
            self.status.setText(tr("viewer.pick_first"))
            return
        QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_query", needle)
        self._cancel_search()
        handle = _SearchHandle()
        self._search_handle = handle
        self._gen += 1
        self._pool.clear()
        self._paths = []
        self._meta = []
        self._search_needle = needle
        self._search_count = 0
        self.list.clear()
        self._pending_thumbs.clear()
        self._pending_dims.clear()
        self._thumb_queued.clear()
        self._thumb_done_rows.clear()
        self._thumbs_done = 0
        self._pixmap = None
        self._movie = None
        self.status.setText(tr("viewer.searching", q=needle))
        QThreadPool.globalInstance().start(
            _SearchTask(base, needle.lower(), self._gen, self._search_signals, handle,
                        ignore_dash=self.ignore_dash_box.isChecked()))

    def _on_ignore_dash_toggled(self, checked: bool) -> None:
        """Переключили чекбокс — запомнить и перезапустить текущий поиск."""
        QSettings("ImageHunter", "ImageHunter").setValue(
            "viewer/search_ignore_dash", bool(checked))
        if self.search_edit.text().strip():
            self._start_search_now()

    def _on_search_batch(self, gen: int, items: list) -> None:
        if gen != self._gen or not items:
            return
        placeholder = QPixmap(THUMB, THUMB)
        placeholder.fill(Qt.darkGray)
        for path, size, mtime in items:
            row = len(self._paths)
            self._paths.append(path)
            self._meta.append((size, mtime))
            item = QListWidgetItem(QIcon(placeholder), os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(os.path.relpath(path, self._folder) if self._folder
                            else os.path.basename(path))
            self.list.addItem(item)
        self._search_count += len(items)
        self.status.setText(tr("viewer.searching_found", q=self._search_needle,
                               n=self._search_count))
        self._schedule_visible_thumbs()
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def _on_search_done(self, gen: int, total: int, truncated: bool) -> None:
        if gen != self._gen:
            return
        self._search_handle = None
        tail = tr("viewer.search_trunc") if truncated else ""
        self.status.setText(tr("viewer.search_done", q=self._search_needle,
                               n=total, tail=tail))
        applog.event("log.event.search_done", q=self._search_needle, n=total)

    # ---------- фильтр папок в дереве «Диски и папки» ----------

    def _escape_search(self) -> None:
        """Esc чистит то поле поиска, где сейчас фокус; в режиме обрезки,
        ресайса или пипетки — сначала выходит из него (v0.8.7, v0.8.6, v0.8.8)."""
        if self._crop_mode:
            self.set_crop_mode(False)
            return
        if self._resize_mode:
            self.set_resize_mode(False)
            return
        if self._picker_mode:
            self.set_picker_mode(False)
            return
        if QApplication.focusWidget() is self.folder_search:
            self.folder_search.clear()
        else:
            self.search_edit.clear()

    def _on_folder_search_text_changed(self, text: str) -> None:
        if text.strip():
            self._fs_timer.start()   # дебаунс: ветви догружаются после паузы в наборе
        else:
            self._fs_timer.stop()
            self._clear_folder_filter()

    def _apply_folder_filter(self) -> None:
        """Оставить в дереве только папки с введёнными буквами в имени.

        Совпадение ищется по загруженным узлам; чтобы буквы находили и
        вложенные папки, дерево догружается, пока хватает бюджета папок
        и секунд (см. _FS_DIR_BUDGET): на обычном домашнем дереве это доли
        секунды, а гигантский или сетевой диск не подвесит окно.
        Совпавшие папки раскрываются вместе со своими предками;
        счётчик совпадений показывается над деревом.

        Область поиска (v0.7.10): буквы ищутся вглубь ВЫДЕЛЕННОЙ папки
        или диска — что подсвечено в дереве, то и обыскивается; чужие
        верхние ветки прячутся целиком и не обходятся вовсе. Ничего
        не выделено — как раньше, по всему дереву. Так фильтр больше не
        шарахается по всем устройствам разом: на сетевом диске он больше
        не платит обходом чужих ветвей и не находит «лишнее» в других
        дисках (репорт: «поиск ищет на всех устройствах, долгий поиск»)."""
        needle = self.folder_search.text().strip().lower()
        if not needle:
            self._clear_folder_filter()
            return
        if self._fs_applying:   # вызов из _populate_children во время прохода
            return
        self._fs_applying = True
        try:
            scope = self._filter_scope()
            # каждый этап — с таймингом: после зависания в журнале видно,
            # что именно тянуло GUI-поток (догрузка дерева или скрытие узлов)
            with applog.timed(tr("perf.op.filter_tree_load"),
                              always=False, slow_ms=400) as tl:
                dirs, budget_hit = self._load_for_filter(scope)
                tl.set(dirs=dirs, budget=budget_hit)
                if dirs:
                    tl.force()   # догрузили ветви — покажем, сколько это заняло
            with applog.timed(tr("perf.op.folder_filter")) as tf:
                n = self._filter_visible(needle, scope)
                tf.set(matched=n)
        finally:
            self._fs_applying = False
        self.tree_info.show()
        if scope is not None:
            where = scope.text(0)
            self.tree_info.setText(tr("viewer.folders_found_in", n=n, where=where) if n
                                   else tr("viewer.folders_none_in", where=where))
            applog.event("log.event.folder_filter_in", q=needle, n=n, where=where)
        else:
            self.tree_info.setText(tr("viewer.folders_found", n=n) if n
                                   else tr("viewer.folders_none"))
            applog.event("log.event.folder_filter", q=needle, n=n)

    def _filter_scope(self):
        """Узел, внутри которого ищет фильтр папок, или None.

        Область задаёт фокус: выделенная в дереве папка (или диск) —
        поиск идёт вглубь только её (v0.7.10). Ничего не выделено —
        ищем по всему дереву, как раньше."""
        item = self.tree.currentItem()
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole):
            return item
        return None

    def _load_for_filter(self, scope=None) -> tuple[int, bool]:
        """Догрузить уровни дерева для фильтра: обход сверху вниз, пока не
        исчерпан бюджет папок/времени. Уже раскрытые папки не перечитываются
        (_populate_children кэшируется), поэтому каждая следующая буква
        почти ничего не стоит. Возвращает (догружено папок, исчерпан ли бюджет).

        С областью (scope — выделенный узел) обход начинается с неё:
        чужие ветки не догружаются вовсе — на сетевом диске это вся
        экономия (v0.7.10)."""
        deadline = time.monotonic() + _FS_TIME_BUDGET
        start = scope if scope is not None else self.tree.invisibleRootItem()
        queue = [start]
        i = 0
        budget = _FS_DIR_BUDGET
        while i < len(queue) and budget > 0 and time.monotonic() <= deadline:
            item = queue[i]
            i += 1
            if item.data(0, Qt.ItemDataRole.UserRole) and \
                    not item.data(0, Qt.ItemDataRole.UserRole + 1):
                self._populate_children_sync(item)   # один scandir на папку
                budget -= 1
            for j in range(item.childCount()):
                child = item.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole):
                    queue.append(child)         # заглушки не обходятся
        return _FS_DIR_BUDGET - budget, budget <= 0

    def _filter_visible(self, needle: str, scope=None) -> int:
        """Скрыть папки без этих букв; совпавшие и их предки остаются видимы,
        ветки к совпавшим раскрываются. Возвращает число совпавших папок.

        С областью (scope — выделенный узел) буквами обыскивается ТОЛЬКО
        его поддерево: путь к фокусу остаётся видим, сестринские ветки и
        все чужие верхние ветки прячутся целиком — совпадений оттуда не
        будет (v0.7.10)."""
        top_of_scope = None
        scope_n = ""
        if scope is not None:
            scope_n = os.path.normcase(
                os.path.normpath(scope.data(0, Qt.ItemDataRole.UserRole) or ""))
            top_of_scope = scope
            while top_of_scope.parent() is not None:
                top_of_scope = top_of_scope.parent()
        n = 0
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top_of_scope is not None and top is not top_of_scope:
                top.setHidden(True)   # вне фокуса — ветка прячется, не обходится
                continue
            if scope is None:
                n += self._filter_item(top, needle)
                continue
            self._hide_outside_scope(top, scope_n)
            n += self._filter_item(scope, needle)
        return n

    def _hide_outside_scope(self, item, scope_n: str) -> None:
        """Спрятать в ветке всё, кроме пути к фокусу: узел-предок scope
        остаётся видим (это дорога к выделенной папке), сестринские ветки
        прячутся целиком; поддерево самого scope не трогается — его
        фильтрует _filter_item."""
        item_n = os.path.normcase(
            os.path.normpath(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        if item_n == scope_n:
            return   # сам фокус — его поддерево фильтруется отдельно
        if self._is_under(scope_n, item_n):   # item — предок scope: путь к фокусу
            for j in range(item.childCount()):
                self._hide_outside_scope(item.child(j), scope_n)
        else:
            item.setHidden(True)

    def _filter_item(self, item, needle: str) -> int:
        """Число совпавших папок в поддереве item (включая сам item)."""
        if not item.data(0, Qt.ItemDataRole.UserRole):   # заглушка загрузки
            item.setHidden(True)
            return 0
        self_match = needle in item.text(0).lower()
        kids = sum(self._filter_item(item.child(j), needle)
                   for j in range(item.childCount()))
        item.setHidden(not (self_match or kids))
        if kids:
            item.setExpanded(True)   # показать ветку к совпавшей папке
        return kids + (1 if self_match else 0)

    def _clear_folder_filter(self) -> None:
        """Убрать фильтр: показать все папки, спрятать счётчик."""
        self.tree_info.hide()

        def unhide(item) -> None:
            for j in range(item.childCount()):
                child = item.child(j)
                child.setHidden(False)
                unhide(child)

        unhide(self.tree.invisibleRootItem())

    def _on_tree_refresh_clicked(self) -> None:
        self.folder_search.clear()   # снимет фильтр, если был активен
        self.refresh_drives()

    def _first_match_item(self, needle: str):
        """Первая видимая совпавшая папка (сверху вниз) — для Enter.
        Скрытые ветки пропускаются целиком: при активной области (фокусе)
        совпадение вне её не откроется и не уведёт в чужой диск."""
        def dfs(item):
            if item.isHidden():
                return None   # ветка скрыта — внутрь не идём
            if item.data(0, Qt.ItemDataRole.UserRole) \
                    and needle in item.text(0).lower():
                return item
            for j in range(item.childCount()):
                found = dfs(item.child(j))
                if found is not None:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            found = dfs(self.tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    def _open_first_folder_result(self) -> None:
        """Enter в поле фильтра — открыть первую (или выделенную) находку."""
        if self._fs_timer.isActive():   # фильтр ещё не применён — применить сейчас
            self._fs_timer.stop()
            self._apply_folder_filter()
        needle = self.folder_search.text().strip().lower()
        item = self._first_match_item(needle) if needle else None
        if item is None:
            cur = self.tree.currentItem()
            if cur is not None and not cur.isHidden() \
                    and cur.data(0, Qt.ItemDataRole.UserRole):
                item = cur
        if item is not None:
            self._on_tree_clicked(item, 0)

    # ---------- ленивые миниатюры: грузим только видимую часть ----------

    def _on_toggle_thumbs(self, checked: bool) -> None:
        """Выключатель предпросмотра; состояние запоминается между запусками."""
        QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", checked)
        self._thumbs_enabled = checked
        if checked:
            self._schedule_visible_thumbs()
        else:
            self._pool.clear()            # не начатые задачи больше не нужны
            self._net_pool.clear()
            self._pending_thumbs.clear()
            self._pending_dims.clear()
            self._thumb_queued.clear()    # при повторном включении их можно повторить
            self._thumb_timer.stop()

    def _schedule_visible_thumbs(self, *_args) -> None:
        """Дебаунс: при прокрутке/ресайзе не пересчитываем видимые строки на каждый пиксель."""
        if self._thumbs_enabled:
            self._visible_timer.start()

    def _on_splitter_moved(self, *_args) -> None:
        """Разделитель передвинут: догрузить видимые миниатюры и запомнить размеры панелей."""
        self._schedule_visible_thumbs()
        QSettings("ImageHunter", "ImageHunter").setValue("viewer/splitter", self.splitter.saveState())

    def _queue_visible_thumbs(self) -> None:
        """Ставит задачи миниатюр ТОЛЬКО для видимых строк (с запасом на экран).

        Так массовая прогрузка предпросмотра отключена: вход в сетевую папку
        с тысячами фотографий читает по сети лишь то, что видно на экране."""
        if not self._thumbs_enabled or not self._paths:
            return
        vp = self.list.viewport().rect()
        if vp.height() <= 0:
            return                        # ещё не показаны — загрузим по showEvent
        margin = vp.height()              # запас по экрану сверху и снизу
        top, bottom = vp.top() - margin, vp.bottom() + margin
        count = self.list.count()
        cache_dir = _thumb_cache_dir()

        # rect.top() монотонно не убывает (раскладка сверху вниз), поэтому
        # первый видимый элемент ищем бинарным поиском: O(log n) вместо O(n)
        lo, hi = 0, count
        while lo < hi:
            mid = (lo + hi) // 2
            if self.list.visualItemRect(self.list.item(mid)).bottom() >= top:
                hi = mid
            else:
                lo = mid + 1
        for row in range(lo, count):
            rect = self.list.visualItemRect(self.list.item(row))
            if rect.top() > bottom:
                break                     # дальше — уже за нижней границей
            if row in self._thumb_queued or row in self._thumb_done_rows:
                continue
            self._thumb_queued.add(row)
            size, mtime = self._meta[row] if row < len(self._meta) else (0, 0.0)
            path = self._paths[row]
            # сетевые файлы — через узкий отдельный пул: пока сервер подвис,
            # локальные миниатюры продолжают грузиться (v0.7.2)
            pool = self._net_pool if _is_remote_path(path) else self._pool
            pool.start(_ThumbTask(path, row, self._gen,
                                  self._thumb_signals, cache_dir, size, mtime))

    # ---------- просмотр ----------

    def step(self, delta: int) -> None:
        if not self._paths:
            return
        row = (self.list.currentRow() + delta) % self.list.count()
        self.list.setCurrentRow(row)

    def _set_view_busy(self, busy: bool) -> None:
        """Курсор занятости на время фоновой загрузки (без вложенных стеков)."""
        if busy and not self._view_busy:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
            self._view_busy = True
        elif not busy and self._view_busy:
            QApplication.restoreOverrideCursor()
            self._view_busy = False

    def _io_pool(self, *paths: str) -> QThreadPool:
        """Пул для файловых операций по путям.

        Сетевые пути (WebDAV/davfs2, SMB, NFS — на Windows с v0.7.2, на
        Linux с v0.8.19) идут через узкий сетевой пул (2 потока): davfs2
        не выдерживает параллельности — слоты запросов кончаются, вызовы
        провисают ~30 с и падают с Errno 11 (EAGAIN). Локальные пути —
        через общий пул. Миниатюры/просмотр раскладывают задачи по пулам
        так же (см. _queue_visible_thumbs и _show_index)."""
        if any(_is_remote_path(p) for p in paths if p):
            return self._net_pool
        return QThreadPool.globalInstance()

    def _show_index(self, row: int) -> None:
        if not (0 <= row < len(self._paths)):
            return
        # выбрали другую картинку — режим ресайса закрывается (v0.8.6):
        # размер задаётся одной конкретной картинке, а не вкладке целиком
        self.set_resize_mode(False)
        self.set_crop_mode(False)   # и обрезка тоже — рамка чужой картинке не нужна (v0.8.7)
        self.set_picker_mode(False)   # и пипетка (v0.8.8)
        self._movie = None
        path = self._paths[row]
        if os.path.splitext(path)[1].lower() == ".gif":
            # GIF читается в фоне (v0.7.11): QMovie(path) валидирует файл в
            # GUI-потоке — на подвисшем сетевом диске это замораживало окно.
            # Анимация построится из памяти в _on_gif_ready.
            self._pixmap = None
            self._movie = None
            self._mode = "fit"
            self._view_inflight += 1
            self._set_view_busy(True)
            self.status.setText(f"{os.path.basename(path)}  •  {tr('viewer.loading')}")
            # сетевой файл — через узкий отдельный пул (v0.7.2, см. _is_remote_path)
            pool = self._net_pool if _is_remote_path(path) else QThreadPool.globalInstance()
            pool.start(_GifTask(path, row, self._gif_signals))
            return
        # большой файл (фото, тем более AVIF, тем более по сети) — декодируем
        # в фоне: интерфейс не подвисает, Windows не пишет «Не отвечает»
        self._view_inflight += 1
        self._set_view_busy(True)
        self.status.setText(f"{os.path.basename(path)}  •  {tr('viewer.loading')}")
        # сетевой файл — через узкий отдельный пул (v0.7.2, см. _is_remote_path)
        pool = self._net_pool if _is_remote_path(path) else QThreadPool.globalInstance()
        pool.start(_ViewTask(path, row, self._view_signals))

    def _on_view_ready(self, row: int, path: str, img: QImage, err: str) -> None:
        self._view_inflight = max(0, self._view_inflight - 1)
        if self._view_inflight == 0:
            self._set_view_busy(False)
        # результат устарел (выбрали другую плитку/папку) — только снять занятость
        if not (0 <= row < len(self._paths)) or self._paths[row] != path:
            return
        # новая картинка — режим ресайса гарантированно закрыт (v0.8.6): пока
        # файл читался, пользователь мог успеть включить его на старой
        self.set_resize_mode(False)
        self.set_crop_mode(False)
        self.set_picker_mode(False)
        if not img.isNull():
            self._pixmap = QPixmap.fromImage(img)
            # прозрачный формат (PNG/GIF/WebP…) — под ним рисуем «шахматку» (v0.7.16)
            self._set_view_checker(img.hasAlphaChannel())
            self._apply_mode()
            self._set_view_status(path, row, self._pixmap.size())
            self.view_label.set_img_size(self._pixmap.size())   # пипетке нужен актуальный размер (v0.8.8)
            self._update_resize_button()   # статичная картинка — «⇲ Размер» доступна
            self._update_crop_button()     # и «✂ Обрезать» тоже (v0.8.7)
            self._update_picker_button()   # и «💧 Пипетка» (v0.8.8)
            if self._crop_continue:        # серия «✂▶ К следующему» (v0.8.7):
                self._crop_continue = False
                if self.btn_crop.isEnabled():
                    self.set_crop_mode(True)   # рамка ждёт на следующей картинке
        elif err:
            self._pixmap = None   # картинки больше нет — и зумить/ресайзить нечего
            self._view_text(tr("viewer.cant_open", err=err))
            self._update_resize_button()
            self._update_crop_button()
            self._update_picker_button()
            self._crop_continue = False   # серия прервалась — картинка не открылась

    def _on_gif_ready(self, row: int, path: str, data: bytes, err: str) -> None:
        """GIF прочитан в фоне — построить анимацию из памяти (QBuffer).

        QMovie не владеет устройством: буфер делается ребёнком самой анимации
        и умирает вместе с ней — отдельной ссылки держать не нужно.
        """
        self._view_inflight = max(0, self._view_inflight - 1)
        if self._view_inflight == 0:
            self._set_view_busy(False)
        # пока читали, выбрали другую плитку/папку — показать нечего
        if not (0 <= row < len(self._paths)) or self._paths[row] != path:
            return
        if err:
            self._pixmap = None
            self._view_text(tr("viewer.cant_open", err=err))
            self._update_resize_button()
            self._update_crop_button()
            self._update_picker_button()
            return
        # анимация — режим ресайса закрыт, кнопка погашена (v0.8.6)
        self.set_resize_mode(False)
        self.set_crop_mode(False)   # GIF не режем — один кадр (v0.8.7)
        self.set_picker_mode(False)   # и цвет GIF-анимации не читаем (v0.8.8)
        self._crop_continue = False   # и серия «к следующему» тоже (v0.8.7)
        buf = QBuffer()
        buf.setData(QByteArray(data))
        buf.open(QBuffer.OpenModeFlag.ReadOnly)
        movie = QMovie(buf)
        if not movie.isValid():
            self._view_text(tr("viewer.cant_open", err="GIF"))
            return
        buf.setParent(movie)   # устройство живёт, пока жива анимация (v0.7.11)
        self._movie = movie
        self.view_label.setMovie(movie)
        movie.start()
        # GIF с прозрачностью — тоже на «шахматке» (v0.7.16): первый кадр
        # знает, есть ли в файле прозрачные пиксели
        self._set_view_checker(movie.currentPixmap().hasAlphaChannel())
        self._set_view_status(path, row, movie.currentPixmap().size())
        self._update_resize_button()   # GIF — «⇲ Размер» недоступна (v0.8.6)
        self._update_crop_button()     # и «✂ Обрезать» тем более (v0.8.7)
        self._update_picker_button()   # и «💧 Пипетка» (v0.8.8)

    def _set_view_status(self, path: str, row: int, size: QSize) -> None:
        self.status.setText(
            f"{os.path.basename(path)}  •  {tr('viewer.of', i=row + 1, n=len(self._paths))}"
            f"  •  {size.width()}×{size.height()}"
        )

    # ---------- фон-«шахматка» (v0.7.16) ----------

    def _set_view_checker(self, on: bool) -> None:
        """Включить/выключить «шахматку» под картинкой (и перестроить плитку).

        Вызывается, когда стало ясно, есть ли у показанной картинки
        альфа-канал, и при смене размера клетки ползунком."""
        self._checker_on = bool(on)
        if self._checker_on:
            self.view_label.set_checker_tile(
                _checker_tile(self._checker_cell,
                              self.view_label.devicePixelRatioF()))
        else:
            self.view_label.set_checker_tile(None)

    def _view_text(self, msg: str) -> None:
        """Текст вместо картинки («Откройте папку…», ошибки чтения) —
        всегда без «шахматки»: квадраты под сообщением только мешают."""
        self._set_view_checker(False)
        self.view_label.setText(msg)

    def _on_checker_cell(self, value: int) -> None:
        """Ползунок размера клеток: запомнить и перерисовать, если видна."""
        self._checker_cell = max(CHECKER_MIN, min(CHECKER_MAX, int(value)))
        QSettings("ImageHunter", "ImageHunter").setValue(
            "viewer/checker_cell", self._checker_cell)
        if self._checker_on:
            self._set_view_checker(True)   # перестроить плитку с новой клеткой

    # ---------- зум ----------
    def _apply_mode(self) -> None:
        if self._movie is not None or self._pixmap is None:
            return
        if self._resize_mode:
            return   # в режиме ресайса показом рулит _apply_resize (v0.8.6)
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
        if self._pixmap is None or self._resize_mode:
            return
        self._mode = "manual"
        self._zoom = max(0.05, min(12.0, self._zoom * factor))
        self._apply_mode()

    def set_manual_zoom(self, value: float) -> None:
        if self._pixmap is None or self._resize_mode:
            return
        self._mode = "manual"
        self._zoom = max(0.05, min(12.0, value))
        self._apply_mode()

    def fit_to_window(self) -> None:
        if self._crop_mode:
            # в обрезке «◱» просто вписывает показ: выделение хранится
            # в координатах картинки и переживает смену зума (v0.8.7)
            self._mode = "fit"
            self._apply_mode()
            return
        if self._resize_mode:
            self.set_resize_mode(False)   # «Вписать» — выход из ресайса (v0.8.6)
            return
        self._mode = "fit"
        self._apply_mode()

    def reveal_folder(self) -> None:
        if self._folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))

    # ---------- изменение размера картинки мышью (v0.8.6) ----------

    def _update_resize_button(self) -> None:
        """Кнопка «⇲ Размер» активна, только пока показана статичная картинка.

        GIF-анимацию менять в размере нельзя (Qt пишет только первый кадр —
        честнее не предлагать), как и пустой просмотр/ошибку чтения."""
        can = self._pixmap is not None and self._movie is None
        self.btn_resize.setEnabled(can)
        if not can and self._resize_mode:
            self.set_resize_mode(False)

    def _on_resize_toggled(self, on: bool) -> None:
        self.set_resize_mode(on)

    def set_resize_mode(self, on: bool) -> None:
        """Включить/выключить режим изменения размера (кнопка и программно).

        В режиме картинка показана «один к одному» в целевом размере — что
        видно, то и запишется. Выход всегда возвращает «Вписать в окно»
        с исходной картинкой; целевой размер не сохраняется между заходами."""
        on = bool(on)
        if on == self._resize_mode:
            return
        if on and self._crop_mode:
            self.set_crop_mode(False)   # режимы «⇲ Размер» и «✂ Обрезать» взаимоисключающие
        if on and self._picker_mode:
            self.set_picker_mode(False)   # и пипетка — тоже режим (v0.8.8)
        if on and (self._pixmap is None or self._movie is not None):
            return   # менять размер нечего: GIF или пустой просмотр
        self._resize_mode = on
        if self.btn_resize.isChecked() != on:
            self.btn_resize.blockSignals(True)
            self.btn_resize.setChecked(on)
            self.btn_resize.blockSignals(False)
        self.view_label.set_resize_mode(on)
        self.btn_resize_save.setVisible(on)
        if on:
            self._resize_orig = QSize(self._pixmap.width(), self._pixmap.height())
            self._resize_size = QSize(self._resize_orig)
            self._resize_saving = False
            self.btn_resize_save.setEnabled(True)
            self._apply_resize(smooth=True)
            self.status.setText(tr("viewer.resize_enter",
                                   new=_dims_text(self._resize_size.width(),
                                                  self._resize_size.height()),
                                   orig=_dims_text(self._resize_orig.width(),
                                                   self._resize_orig.height())))
        else:
            self._resize_size = None
            self._resize_orig = None
            self._resize_handle = 0
            self._resize_start = None
            self._resize_saving = False
            self.view_label.set_size_badge("")
            self._mode = "fit"
            self._apply_mode()

    def _apply_resize(self, smooth: bool = False) -> None:
        """Показать картинку в целевом размере (WYSIWYG: пиксмап = будущий файл).

        Во время перетаскивания масштаб быстрый (FastTransformation) — плавность
        важнее качества; на отпускании кнопки (и при входе в режим) проход
        гладкий (SmoothTransformation). Бейдж у угла рамки дублирует размер."""
        if not self._resize_mode or self._pixmap is None or self._resize_size is None:
            return
        w, h = self._resize_size.width(), self._resize_size.height()
        scaled = self._pixmap.scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation if smooth
            else Qt.TransformationMode.FastTransformation)
        if scaled.isNull():
            return
        self.view_label.setPixmap(scaled)
        self.view_label.resize(scaled.size())
        self.view_label.set_size_badge(f"{w}×{h}")
        orig = self._resize_orig
        self.status.setText(tr(
            "viewer.resize_status", new=_dims_text(w, h),
            orig=_dims_text(orig.width(), orig.height()) if orig else "—"))

    def _on_resize_start(self, handle: int) -> None:
        """Рукоятка захвачена — запомнить размер на старте перетаскивания."""
        if not self._resize_mode or self._resize_size is None:
            return
        self._resize_handle = handle
        self._resize_start = QSize(self._resize_size)

    def _on_resize_drag(self, dx: int, dy: int) -> None:
        """Мышь поехала: пересчитать целевой размер по типу рукоятки."""
        if (not self._resize_mode or self._resize_handle == 0
                or self._resize_start is None or self._resize_orig is None):
            return
        self._resize_size = _resize_target_for(
            self._resize_handle, self._resize_start, dx, dy, self._resize_orig)
        self._apply_resize(smooth=False)   # быстрый масштаб на лету

    def _on_resize_release(self) -> None:
        """Кнопка отпущена — финальный гладкий масштаб нового размера."""
        if self._resize_handle == 0:
            return
        self._resize_handle = 0
        self._resize_start = None
        self._apply_resize(smooth=True)

    def _on_resize_save(self) -> None:
        """«💾 Сохранить»: записать картинку нового размера рядом с оригиналом.

        Имя — «имя_ШxВ.ext» (расширение оригинала; AVIF Qt не пишет — уедет
        в PNG). Само масштабирование и запись выполняет рабочий поток
        (_ResizeSaveTask): GUI не ждёт ни SmoothTransformation на большом
        фото, ни сетевой диск. Оригинал не трогается, существующие файлы
        не затираются (свободное имя выбирается перед самой записью)."""
        if (not self._resize_mode or self._resize_size is None
                or self._pixmap is None):
            return
        if self._resize_saving:
            self.status.setText(tr("viewer.resize_saving"))
            return
        row = self.list.currentRow()
        src = self._paths[row] if 0 <= row < len(self._paths) else ""
        folder = os.path.dirname(src) if src else self._folder
        if not folder or not os.path.isdir(folder):
            self.status.setText(tr("viewer.resize_save_err",
                                   err=os.path.basename(src) or "—"))
            applog.error(tr("log.event.resize_err",
                            name=os.path.basename(src) or "—",
                            err="папка недоступна"))
            return
        self._resize_saving = True
        self.btn_resize_save.setEnabled(False)
        self.status.setText(tr("viewer.resize_saving"))
        stem = os.path.splitext(os.path.basename(src))[0] if src else "image"
        ext = _resize_save_ext(os.path.splitext(src)[1]) if src else ".png"
        QThreadPool.globalInstance().start(_ResizeSaveTask(
            self._pixmap.toImage(), self._resize_size.width(),
            self._resize_size.height(), folder, stem, ext,
            os.path.basename(src) or "—", self._resize_signals))

    def _on_resize_save_done(self, ok: bool, path: str, w: int, h: int,
                             err: str) -> None:
        """Фоновая запись закончилась: статус, лента обновится, режим закроется.

        После успеха режим ресайса закрывается (исходник снова «вписан»),
        лента пересканируется, и новый файл открывается в просмотре — сразу
        видно результат. При ошибке режим остаётся открытым: размер на месте,
        можно поправить и сохранить снова."""
        self._resize_saving = False
        self.btn_resize_save.setEnabled(True)
        if ok:
            self.status.setText(tr("viewer.resize_saved",
                                   name=os.path.basename(path), w=w, h=h))
            self.set_resize_mode(False)
            self.refresh()   # новый файл появится в ленте
            # отложенный выбор — ПОСЛЕ refresh(): load_folder внутри него
            # чистит поле, а цель нужен только скану, который приедет позже
            self._select_after_scan = path
        else:
            self.status.setText(tr("viewer.resize_save_err", err=err))

    # ---------- обрезка картинки мышью, как в XnView (v0.8.7) ----------

    def _update_crop_button(self) -> None:
        """Кнопка «✂ Обрезать» активна, только пока показана статичная картинка.

        GIF обрезать нельзя (Qt пишет один кадр — честнее не предлагать),
        пустой просмотр/ошибка чтения — тем более."""
        can = self._pixmap is not None and self._movie is None
        self.btn_crop.setEnabled(can)
        if not can and self._crop_mode:
            self.set_crop_mode(False)
        # флаг серии «✂▶ К следующему» здесь НЕ гасится: он должен пережить
        # пересканирование той же папки (pixmap на это время пуст) — его гасят
        # только смена папки (load_folder), GIF и ошибка чтения (v0.8.7)

    def _on_crop_toggled(self, on: bool) -> None:
        self.set_crop_mode(on)

    def set_crop_mode(self, on: bool) -> None:
        """Включить/выключить режим обрезки (кнопка и программно).

        Режимы «⇲ Размер» и «✂ Обрезать» взаимоисключающие: вход в один
        закрывает другой. Показ картинки в режиме НЕ меняется (зум работает
        как обычно) — выделение хранится в координатах картинки и переживает
        смену зума; между заходами выделение не сохраняется."""
        on = bool(on)
        if on == self._crop_mode:
            return
        if on and (self._pixmap is None or self._movie is not None):
            return   # обрезать нечего: GIF или пустой просмотр
        if on and self._resize_mode:
            self.set_resize_mode(False)
        if on and self._picker_mode:
            self.set_picker_mode(False)   # пипетка и обрезка взаимоисключающие (v0.8.8)
        self._crop_mode = on
        if self.btn_crop.isChecked() != on:
            self.btn_crop.blockSignals(True)
            self.btn_crop.setChecked(on)
            self.btn_crop.blockSignals(False)
        self.view_label.set_crop_mode(
            on, self._pixmap.size() if (on and self._pixmap is not None) else None)
        for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                  self.btn_wm_sel, self.btn_crop_next):
            b.setVisible(on)
            b.setEnabled(False)   # включатся, когда появится выделение
        if on:
            self._crop_saving = False
            self.status.setText(tr("viewer.crop_enter"))
        else:
            self._crop_saving = False

    def _on_crop_selection_changed(self) -> None:
        """Выделение изменилось: статус «✂ 409×275 из …» и доступность кнопок."""
        if not self._crop_mode:
            return
        sel = self.view_label.selection()
        has = not sel.isNull() and self._pixmap is not None
        for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                  self.btn_wm_sel, self.btn_crop_next):
            b.setEnabled(has and not self._crop_saving and not self._fill_saving)
        if self._crop_saving:
            return
        if has:
            orig = self._pixmap.size()
            self.status.setText(tr("viewer.crop_status",
                                   sel=_dims_text(sel.width(), sel.height()),
                                   orig=_dims_text(orig.width(), orig.height())))
        else:
            self.status.setText(tr("viewer.crop_none"))

    def _on_crop_apply(self) -> None:
        self._crop_save("")

    def _on_crop_apply_next(self) -> None:
        """«✂▶ К следующему»: сохранить выделенное и открыть следующую картинку.

        Режим обрезки остаётся включённым — папку целиком можно пройти одним
        потоком, как в XnView («Обрезать, Сохранить и перейти к следующему»).
        Если это была последняя картинка, серия честно заканчивается."""
        row = self.list.currentRow()
        self._crop_next_row = row + 1
        self._crop_continue = True
        self._crop_save("")

    def _on_crop_save_as(self) -> None:
        """«💾 Как…»: имя и папка результата — через стандартный диалог.

        По умолчанию предлагается «имя_crop.ext» рядом с оригиналом; Qt сам
        спросит подтверждение, если такой файл уже существует."""
        if not self._crop_mode or not self.view_label.has_selection():
            return
        row = self.list.currentRow()
        src = self._paths[row] if 0 <= row < len(self._paths) else ""
        folder = os.path.dirname(src) if src else (self._folder or "")
        stem = os.path.splitext(os.path.basename(src))[0] if src else "image"
        ext = _resize_save_ext(os.path.splitext(src)[1]) if src else ".png"
        path, _fltr = QFileDialog.getSaveFileName(
            self, tr("viewer.crop_saveas_title"),
            os.path.join(folder, f"{stem}_{_CROP_SUFFIX}{ext}"),
            tr("viewer.crop_saveas_filter"))
        if path:
            self._crop_save(path)

    def _crop_save(self, dst_path: str) -> None:
        """Записать выделенную область — общий хвост «Сохранить»/«Как…»/«К следующему».

        Вырезание и запись выполняет рабочий поток (_CropSaveTask): GUI не
        ждёт ни QImage.copy большого фото, ни сетевой диск (принцип v0.7.2).
        Оригинал не меняется; без явного пути свободное имя «имя_crop.ext»
        выбирается непосредственно перед записью — ничего не затирается."""
        if (not self._crop_mode or self._pixmap is None
                or not self.view_label.has_selection()):
            return
        if self._crop_saving:
            self.status.setText(tr("viewer.crop_saving"))
            return
        row = self.list.currentRow()
        src = self._paths[row] if 0 <= row < len(self._paths) else ""
        folder = os.path.dirname(src) if src else self._folder
        if not dst_path and (not folder or not os.path.isdir(folder)):
            self.status.setText(tr("viewer.crop_save_err",
                                   err=os.path.basename(src) or "—"))
            applog.error(tr("log.event.crop_err",
                            name=os.path.basename(src) or "—",
                            err="папка недоступна"))
            return
        self._crop_saving = True
        for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                  self.btn_wm_sel, self.btn_crop_next):
            b.setEnabled(False)
        self.status.setText(tr("viewer.crop_saving"))
        stem = os.path.splitext(os.path.basename(src))[0] if src else "image"
        ext = _resize_save_ext(os.path.splitext(src)[1]) if src else ".png"
        QThreadPool.globalInstance().start(_CropSaveTask(
            self._pixmap.toImage(), self.view_label.selection(), folder,
            stem, ext, os.path.basename(src) or "—", self._crop_signals,
            dst_path))

    def _on_crop_save_done(self, ok: bool, path: str, w: int, h: int,
                           err: str) -> None:
        """Фоновая запись закончилась: статус и обновление ленты.

        «💾 Сохранить»/«💾 Как…»: режим закрывается, лента пересканируется,
        новый файл открывается в просмотре. «✂▶ К следующему»: режим
        остаётся — после пересканирования откроется СЛЕДУЮЩАЯ картинка
        папки, рамка чистая, можно обрезать дальше. При ошибке режим и
        выделение на месте — можно поправить и сохранить снова."""
        self._crop_saving = False
        if ok:
            name = os.path.basename(path)
            batch = self._crop_continue
            nxt = (self._paths[self._crop_next_row]
                   if batch and 0 <= self._crop_next_row < len(self._paths)
                   else "")
            self._crop_next_row = -1
            if batch and nxt:
                self.status.setText(tr("viewer.crop_saved_next",
                                       name=name, w=w, h=h))
                self.refresh()   # новый файл появится в ленте
                # отложенный выбор — ПОСЛЕ refresh(): load_folder внутри него
                # чистит поле, а цель нужен только скану, который приедет позже
                self._select_after_scan = nxt   # серия продолжится сама
            else:
                if batch:
                    self._crop_continue = False   # папка кончилась — серия закрыта
                self.status.setText(tr("viewer.crop_saved_end" if batch
                                       else "viewer.crop_saved",
                                       name=name, w=w, h=h))
                self.set_crop_mode(False)
                self.refresh()
                self._select_after_scan = path
        else:
            for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                      self.btn_wm_sel, self.btn_crop_next):
                b.setEnabled(self.view_label.has_selection()
                             and not self._fill_saving)
            self.status.setText(tr("viewer.crop_save_err", err=err))

    # ---------- пипетка: цвет пикселя (v0.8.8) ----------

    def _update_picker_button(self) -> None:
        """Кнопка «💧 Пипетка» активна, только пока показана статичная картинка.

        Цвет GIF-анимации читать не у чего честного (кадры мелькают),
        пустой просмотр/ошибка чтения — тем более."""
        can = self._pixmap is not None and self._movie is None
        self.btn_picker.setEnabled(can)
        if not can and self._picker_mode:
            self.set_picker_mode(False)

    def _on_picker_toggled(self, on: bool) -> None:
        self.set_picker_mode(on)

    def set_picker_mode(self, on: bool) -> None:
        """Включить/выключить режим пипетки (кнопка и программно).

        В режиме курсор над картинкой — крестик, наведение показывает цвет
        пикселя в статусе, клик берёт цвет (образец на панели + буфер
        обмена). Режимы «💧 Пипетка», «✂ Обрезать» и «⇲ Размер»
        взаимоисключающие; взятый ЦВЕТ переживает выход из режима."""
        on = bool(on)
        if on == self._picker_mode:
            return
        if on and (self._pixmap is None or self._movie is not None):
            return   # читать цвет нечего: GIF или пустой просмотр
        if on and self._crop_mode:
            self.set_crop_mode(False)
        if on and self._resize_mode:
            self.set_resize_mode(False)
        self._picker_mode = on
        if self.btn_picker.isChecked() != on:
            self.btn_picker.blockSignals(True)
            self.btn_picker.setChecked(on)
            self.btn_picker.blockSignals(False)
        self.view_label.set_picker_mode(on)
        if on:
            # источник чтения — своя копия картинки: pixelColor по пиксмапу
            # показа даёт интерполированный цвет, нужен оригинал
            self._picker_img = self._pixmap.toImage()
            self.status.setText(tr("viewer.picker_enter"))
        else:
            self._picker_img = None   # копия оригинала нужна только в режиме

    def _on_picker_hover(self, p: QPoint, inside: bool) -> None:
        """Мышь в режиме пипетки: живой цвет под курсором — в статус."""
        if not self._picker_mode:
            return
        if time.monotonic() < self._picker_hold:
            return   # только что взятый цвет не гасится мгновенно
        img = self._picker_img
        if (not inside or img is None or img.isNull()
                or not (0 <= p.x() < img.width() and 0 <= p.y() < img.height())):
            return
        c = img.pixelColor(p)
        if c.isValid():
            self.status.setText(tr("viewer.picker_hover", hex=c.name(),
                                   x=p.x(), y=p.y()))

    def _on_picker_pick(self, p: QPoint) -> None:
        """Цвет взят: клик в режиме «💧 Пипетка» ИЛИ правый клик по картинке.

        Правый клик работает в любом режиме (обрезка, ресайс, простой
        просмотр) — не выходить же из обрезки ради одного клика. Цвет
        запоминается (его использует «🪣 Закрасить»), показывается
        образцом на панели и копируется в буфер обмена как «#rrggbb»."""
        if self._pixmap is None or self._movie is not None:
            return
        img = self._picker_img
        if img is None or img.isNull() or img.size() != self._pixmap.size():
            img = self._pixmap.toImage()   # разовое чтение — копия не хранится
            if img.isNull():
                return
            if self._picker_mode:
                self._picker_img = img
        x = max(0, min(img.width() - 1, int(p.x())))
        y = max(0, min(img.height() - 1, int(p.y())))
        c = img.pixelColor(x, y)
        if not c.isValid():
            return
        self._picker_color = QColor(c)
        hexs = self._picker_color.name()
        QApplication.clipboard().setText(hexs)
        self._picker_hold = time.monotonic() + _PICKER_HOLD_S
        self._update_picker_chip()
        self.status.setText(tr("viewer.picker_picked", hex=hexs, x=x, y=y))

    def _update_picker_chip(self) -> None:
        """Образец взятого цвета на панели: цветной квадрат + HEX."""
        c = self._picker_color
        if c is None or not c.isValid():
            self.picker_swatch.setVisible(False)
            self.picker_hex.setVisible(False)
            return
        hexs = c.name()
        self.picker_swatch.setStyleSheet(
            f"background-color: {hexs}; border: 1px solid #888; border-radius: 3px;")
        self.picker_hex.setText(hexs)
        self.picker_swatch.setVisible(True)
        self.picker_hex.setVisible(True)

    # ---------- закрашивание выделенной области цветом пипетки (v0.8.8) ----------

    def _on_fill_apply(self) -> None:
        """«🪣 Закрасить»: залить выделенную область цветом пипетки.

        Закрашивание делается сразу в показе (WYSIWYG): область становится
        ровно взятого цвета — что видно, то и запишется. Запись выполняет
        рабочий поток (_FillSaveTask): результат — отдельный файл
        «имя_fill.ext» рядом с оригиналом, сам оригинал не меняется.
        Без взятого цвета — честная подсказка: сначала пипетка."""
        if (not self._crop_mode or self._pixmap is None
                or not self.view_label.has_selection()):
            return
        if self._picker_color is None:
            self.status.setText(tr("viewer.fill_nocolor"))
            return
        if self._fill_saving:
            self.status.setText(tr("viewer.fill_saving"))
            return
        row = self.list.currentRow()
        src = self._paths[row] if 0 <= row < len(self._paths) else ""
        folder = os.path.dirname(src) if src else self._folder
        if not folder or not os.path.isdir(folder):
            self.status.setText(tr("viewer.fill_save_err",
                                   err=os.path.basename(src) or "—"))
            applog.error(tr("log.event.fill_err",
                            name=os.path.basename(src) or "—",
                            err="папка недоступна"))
            return
        sel = self.view_label.selection()
        old_pm = self._pixmap
        img = old_pm.toImage()
        if img.isNull():
            self.status.setText(tr("viewer.fill_save_err",
                                   err=tr("viewer.cant_open", err="—")))
            return
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        c = QColor(self._picker_color)
        c.setAlpha(255)   # закрашивание непрозрачное — ровно как показывает образец
        p.fillRect(sel, c)
        p.end()
        new_pm = QPixmap.fromImage(img)
        if new_pm.isNull():
            self.status.setText(tr("viewer.fill_save_err",
                                   err=tr("viewer.cant_open", err="—")))
            return
        self._fill_prev_pixmap = old_pm   # при ошибке записи показ вернётся к оригиналу
        self._pixmap = new_pm
        self._apply_mode()   # закрашенное видно сразу, до записи
        self._fill_saving = True
        for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                  self.btn_wm_sel, self.btn_crop_next):
            b.setEnabled(False)
        self.status.setText(tr("viewer.fill_saving"))
        stem = os.path.splitext(os.path.basename(src))[0] if src else "image"
        ext = _resize_save_ext(os.path.splitext(src)[1]) if src else ".png"
        QThreadPool.globalInstance().start(_FillSaveTask(
            img, folder, stem, ext, os.path.basename(src) or "—",
            self._fill_signals))

    def _on_fill_save_done(self, ok: bool, path: str, w: int, h: int,
                           err: str) -> None:
        """Фоновая запись закрашенной картинки закончилась.

        Успех: режим закрывается, лента пересканируется, результат
        открывается в просмотре. Ошибка: показ честно откатывается к
        оригиналу (в файле ничего нет — показывать закрашенное нельзя),
        режим и выделение на месте — можно поправить и попробовать снова."""
        self._fill_saving = False
        has = self.view_label.has_selection()
        for b in (self.btn_crop_save, self.btn_crop_saveas, self.btn_fill,
                  self.btn_wm_sel, self.btn_crop_next):
            b.setEnabled(has and not self._crop_saving)
        if ok:
            self._fill_prev_pixmap = None
            self.status.setText(tr("viewer.fill_saved",
                                   name=os.path.basename(path), w=w, h=h))
            self.set_crop_mode(False)
            self.refresh()   # новый файл появится в ленте
            # отложенный выбор — ПОСЛЕ refresh(): load_folder внутри него
            # чистит поле, а цель нужен только скану, который приедет позже
            self._select_after_scan = path
        else:
            prev = self._fill_prev_pixmap
            self._fill_prev_pixmap = None
            if prev is not None:
                self._pixmap = prev
                self._apply_mode()
            self.status.setText(tr("viewer.fill_save_err", err=err))

    # ---------- дерево дисков и папок ----------

    def refresh_drives(self, include_all: bool = False) -> None:
        """Перечитает диски/устройства и быстрые ссылки (Домой, Изображения).

        Сами тома перечисляются фоном (v0.7.14, см. _DrivesTask): QStorageInfo
        на сетевом диске заминал GUI на сетевой тайм-аут. Секция дисков
        строится из кэша последнего перечисления — при старте она появится
        на экране мгновенно, как только рабочая задача пришлёт список,
        при повторных вызовах (смена языка, ⟳) — сразу, без сети."""
        with applog.timed(tr("perf.op.refresh_drives")) as t:
            self.tree.clear()

            # избранные папки — самыми первыми в дереве (v0.7.9)
            for k, fav in enumerate(self._favorites):
                self._add_fav_item(fav, at=k)

            home = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)
            pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
            if home and os.path.isdir(home):
                self._add_folder_item(None, home, title=tr("viewer.home"),
                                      icon=QStyle.StandardPixmap.SP_DirHomeIcon)
            if pics and os.path.isdir(pics) and os.path.normpath(pics) != os.path.normpath(home):
                self._add_folder_item(None, pics, title=tr("viewer.pictures"))

            for drive in self._drives_cache:
                self._add_drive_item_data(*drive)
            if self._folder and os.path.isdir(self._folder):
                self._sync_tree_async(self._folder)   # подсветить текущую папку заново (без замираний, v0.7.6)
            if self.folder_search.text().strip():
                self._apply_folder_filter()   # дерево перечитано — фильтр заново
            t.set(roots=self.tree.topLevelItemCount())
        # перечисление дисков — в рабочем потоке (v0.7.14): обновит секцию
        # в _on_drives_ready, когда пришлёт актуальный список
        QThreadPool.globalInstance().start(
            _DrivesTask(self._drives_signals, include_all))

    def _on_drives_ready(self, drives: list) -> None:
        """Список дисков пришёл из рабочего потока — обновить секцию дерева.

        Сравнивается НАБОР дисков (путь + подпись): свободное место на
        диске плавает между перечислениями, полное сравнение пересоздавало
        бы секцию каждый раз и сворачивало раскрытые ветви. Набор тот же —
        только освежается статистика объёма в подсказках; изменился —
        секция пересобирается, затем асинхронная подсветка текущей папки
        и активный фильтр заново (секция-то переезжала)."""
        same_set = ([(d[0], d[1]) for d in drives]
                    == [(d[0], d[1]) for d in self._drives_cache])
        if same_set:
            if not drives:
                return
            by_path: dict = {}
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, _DRIVE_ROLE):
                    by_path[it.data(0, Qt.ItemDataRole.UserRole)] = it
            for path, _label, total, free in drives:
                it = by_path.get(path)
                if it is None:
                    continue
                tip = path
                if total > 0:
                    tip += "\n" + tr("viewer.free_space",
                                     free=_fmt_bytes(free), total=_fmt_bytes(total))
                it.setToolTip(0, tip)
            self._drives_cache = drives
            return
        self._drives_cache = drives
        for i in range(self.tree.topLevelItemCount() - 1, -1, -1):
            if self.tree.topLevelItem(i).data(0, _DRIVE_ROLE):
                self.tree.takeTopLevelItem(i)
        for drive in drives:
            self._add_drive_item_data(*drive)
        if self._folder and os.path.isdir(self._folder):
            self._sync_tree_async(self._folder)
        if self.folder_search.text().strip():
            self._apply_folder_filter()

    # ---------- избранные папки (v0.7.9) ----------

    @staticmethod
    def _load_favorites() -> list[str]:
        """Избранные папки из настроек.

        QSettings в INI-формате (Linux) отдаёт список из одного элемента
        просто строкой — здесь он снова становится списком; мусор и пустые
        строки отбрасываются, порядок сохраняется."""
        raw = QSettings("ImageHunter", "ImageHunter").value(_FAV_KEY, [])
        if isinstance(raw, str):
            raw = [raw] if raw else []
        out: list[str] = []
        for p in raw or []:
            if isinstance(p, str) and p and p not in out:
                out.append(p)
        return out

    def _save_favorites(self) -> None:
        QSettings("ImageHunter", "ImageHunter").setValue(_FAV_KEY, self._favorites)

    @staticmethod
    def _fav_key(path: str) -> str:
        """Ключ сравнения папок: регистр и вид слешей не важны (Windows)."""
        return os.path.normcase(os.path.normpath(path))

    def is_favorite(self, folder: str) -> bool:
        key = self._fav_key(folder)
        return any(self._fav_key(f) == key for f in self._favorites)

    def fav_add(self, folder: str) -> None:
        """Добавить папку в избранное: с золотой звездой она встанет вверху
        дерева «Диски и папки», до «Домой» и списка дисков.

        Повторное добавление той же папки (даже в другом написании пути)
        ничего не меняет. Дерево перестраивается точечно — только секция
        избранного: полный refresh_drives свернул бы раскрытые ветви, а на
        сетевом диске ещё и оплатил бы это сетевыми тайм-аутами."""
        folder = os.path.normpath(folder) if folder else ""
        if not folder:
            return
        key = self._fav_key(folder)
        if any(self._fav_key(f) == key for f in self._favorites):
            return
        self._favorites.append(folder)
        self._save_favorites()
        self._rebuild_favorites()
        if self.folder_search.text().strip():
            self._apply_folder_filter()   # новый узел — тоже под фильтр
        applog.event("log.event.fav_add",
                     folder=os.path.basename(folder) or folder,
                     n=len(self._favorites))

    def fav_remove(self, folder: str) -> None:
        """Убрать папку из избранного (сама папка, разумеется, не трогается)."""
        key = self._fav_key(folder)
        removed = [f for f in self._favorites if self._fav_key(f) == key]
        if not removed:
            return
        self._favorites = [f for f in self._favorites if self._fav_key(f) != key]
        self._save_favorites()
        self._rebuild_favorites()
        if self.folder_search.text().strip():
            self._apply_folder_filter()
        applog.event("log.event.fav_remove",
                     folder=os.path.basename(removed[0]) or removed[0],
                     n=len(self._favorites))
        # убрали папку, внутри которой (или равной которой) мы сейчас
        # находимся, — вернуть подсветку к текущей папке; прогулка
        # асинхронная, интерфейс не замирает (v0.7.6)
        if self._folder:
            folder_n = self._fav_key(self._folder)
            if any(folder_n == self._fav_key(f)
                   or self._is_under(folder_n, self._fav_key(f)) for f in removed):
                self._sync_tree_async(self._folder)

    def _rebuild_favorites(self) -> None:
        """Перестроить секцию избранного вверху дерева, не трогая диски и
        уже раскрытые ветви (см. fav_add)."""
        for i in range(self.tree.topLevelItemCount() - 1, -1, -1):
            if self.tree.topLevelItem(i).data(0, _FAV_ROLE):
                self.tree.takeTopLevelItem(i)
        for k, fav in enumerate(self._favorites):
            self._add_fav_item(fav, at=k)

    def _add_fav_item(self, path: str, at: int | None = None) -> None:
        item = QTreeWidgetItem([os.path.basename(path) or path])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, _FAV_ROLE, True)
        item.setIcon(0, _star_icon())
        item.setToolTip(0, path)
        item.addChild(self._dummy_item())   # раскрывается как обычная папка
        if at is None:
            self.tree.addTopLevelItem(item)
        else:
            self.tree.insertTopLevelItem(at, item)

    def _on_fav_button(self) -> None:
        """Кнопка ☆/★ в шапке дерева: избранное для папки, открытой сейчас."""
        if not self._folder:
            return
        if self.is_favorite(self._folder):
            self.fav_remove(self._folder)
        else:
            self.fav_add(self._folder)
        self._update_fav_button()   # звезда переключается сразу, без перезагрузки папки

    def _update_fav_button(self) -> None:
        """Состояние ☆/★: нажимается, когда папка открыта; залита, когда
        папка уже в избранном."""
        if self._folder and self.is_favorite(self._folder):
            self.btn_fav.setText("★")
            self.btn_fav.setToolTip(tr("viewer.fav_remove_tip"))
            self.btn_fav.setEnabled(True)
        else:
            self.btn_fav.setText("☆")
            self.btn_fav.setToolTip(tr("viewer.fav_add_tip"))
            self.btn_fav.setEnabled(bool(self._folder))

    def _tree_context_menu(self, pos) -> None:
        """Правый клик в дереве «Диски и папки»: добавить/убрать ЭТУ папку
        в избранном — удобно для вложенных папок, куда кнопка ☆ (текущая
        папка) не дотягивается."""
        item = self.tree.itemAt(pos)
        path = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not path:
            return
        menu = QMenu(self)
        if self.is_favorite(path):
            act = menu.addAction(tr("viewer.fav_remove"))
        else:
            act = menu.addAction(tr("viewer.fav_add"))
        if menu.exec(self.tree.mapToGlobal(pos)) is act:
            if self.is_favorite(path):
                self.fav_remove(path)
            else:
                self.fav_add(path)

    def _add_drive_item_data(self, path: str, label: str, total: int,
                             free: int) -> None:
        """Добавить узел диска из данных фоновой задачи _DrivesTask."""
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, _DRIVE_ROLE, True)
        item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        tip = path
        if total > 0:
            tip += "\n" + tr("viewer.free_space", free=_fmt_bytes(free), total=_fmt_bytes(total))
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

    def _populate_children(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        """Ленивая загрузка подпапок при раскрытии — scandir в рабочем потоке.

        Чтение подпапок по сети (WebDAV, SMB) может занять секунды, а на
        подвисшем сервере — сетевой тайм-аут целиком, поэтому узел дерева
        заполняется асинхронно: клик и раскрытие интерфейс не заминают
        (v0.7.2). Фильтр папок и подсветка текущей папки используют
        синхронный вариант — им результат нужен немедленно
        (см. _populate_children_sync)."""
        if item.data(0, Qt.ItemDataRole.UserRole + 1):  # уже раскрывали / уже сканируем
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        self._tree_token += 1
        token = self._tree_token
        item.setData(0, _TREE_TOKEN_ROLE, token)
        while item.childCount():
            item.removeChild(item.child(0))   # убираем старую заглушку
        item.addChild(self._dummy_item())     # узел выглядит раскрываемым, пока читаем
        self._io_pool(path).start(
            _SubdirsTask(path, token, item, self._subdir_signals))

    def _on_subdirs_ready(self, token: int, item, path: str, subs: list) -> None:
        """Подпапки прочитаны в фоне — достроить узел дерева (узел мог умереть)."""
        try:
            if not shiboken6.isValid(item):
                return                        # дерево уже перестроено (refresh_drives)
        except RuntimeError:
            return
        if item.data(0, _TREE_TOKEN_ROLE) != token:
            return                            # узел уже перечитали заново
        while item.childCount():
            item.removeChild(item.child(0))
        dir_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        for sub in subs:
            child = QTreeWidgetItem([os.path.basename(sub)])
            child.setData(0, Qt.ItemDataRole.UserRole, sub)
            child.setIcon(0, dir_icon)
            child.setToolTip(0, sub)
            child.addChild(self._dummy_item())
            item.addChild(child)
        if item.data(0, _TREE_SYNC_ROLE):
            self._sync_continue(item)         # асинхронная прогулка к папке
        if self.folder_search.text().strip() and not self._fs_applying:
            self._apply_folder_filter()       # новые подпапки — тоже под фильтр

    def _populate_children_sync(self, item: QTreeWidgetItem) -> None:
        """Синхронное чтение подпапок — для фильтра папок и подсветки текущей

        папки, которым результат нужен немедленно. Обход ограничен бюджетом
        вызывающего (см. _load_for_filter), но подвисший сервер всё же может
        задержать вызов — поэтому из кликов он больше не вызывается.

        Если узел уже помечен асинхронной догрузкой (UserRole+1), но дети
        ещё не приехали (только заглушка фоновой задачи, v0.7.14: после
        refresh_drives async-прогулка успела пометить корень раньше
        синхронной подсветки), узел перечитывается синхронно, а жетон
        поднимается — поздний фоновый результат не перезапишет детей."""
        started = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if started and self._children_loaded(item):
            return
        item.setData(0, Qt.ItemDataRole.UserRole + 1, True)
        if started:
            self._tree_token += 1          # см. докстринг: отменяем фоновую догрузку
            item.setData(0, _TREE_TOKEN_ROLE, self._tree_token)
        while item.childCount():
            item.removeChild(item.child(0))  # убираем заглушку
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        # scandir по папке может тянуться (сеть, проснувшийся диск) — замерим,
        # в журнал пишем только заметно медленные (обычные проходят за миллисекунды)
        with applog.timed(tr("perf.op.populate_children",
                             folder=os.path.basename(path) or path),
                          always=False, slow_ms=400) as tp:
            scan_t0 = time.perf_counter()
            subs = self._list_subdirs(path)
            dir_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            for sub in subs:
                child = QTreeWidgetItem([os.path.basename(sub)])
                child.setData(0, Qt.ItemDataRole.UserRole, sub)
                child.setIcon(0, dir_icon)
                child.setToolTip(0, sub)
                child.addChild(self._dummy_item())
                item.addChild(child)
            tp.set(dirs=len(subs),
                   scan_ms=round((time.perf_counter() - scan_t0) * 1000))
        if self.folder_search.text().strip() and not self._fs_applying:
            self._apply_folder_filter()   # новые подпапки — тоже под фильтр

    @staticmethod
    def _list_subdirs(path: str) -> list[str]:
        """Подпапки одним проходом os.scandir — без stat() на каждый элемент
        (на сетевом диске каждый stat — сетевой round-trip)."""
        out = []
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.name.startswith(".") or _is_hidden_entry(entry):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            out.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            return []
        out.sort(key=lambda p: natural_key(os.path.basename(p)))
        return out

    @staticmethod
    def _children_loaded(item: QTreeWidgetItem) -> bool:
        """Дети узла реально прочитаны (есть хоть один настоящий ребёнок:
        заглушка фоновой догрузки UserRole пуста)."""
        for i in range(item.childCount()):
            if item.child(i).data(0, Qt.ItemDataRole.UserRole):
                return True
        return False

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._sync_seq += 1   # ручной выбор — запоздалые шаги прогулки не перебьют
        self._populate_children(item)
        item.setExpanded(True)
        self._folder = path
        self._update_fav_button()
        # фокус сменился — сменилась и область фильтра папок (v0.7.10):
        # с тем же текстом textChanged не сработает, применяем принудительно
        if self.folder_search.text().strip() and not self._fs_applying:
            self._apply_folder_filter()
        if self.search_edit.text().strip():
            self._start_search_now()   # поиск от заново выбранной папки
        else:
            self.load_folder(path)

    def _restore_last_folder(self) -> None:
        """Автопоказ последней открытой папки: скан в рабочем потоке, чтобы
        запуск оставался мгновенным даже на сетевом диске (v0.7.2). Пустая
        или гигантская (> _RESTORE_MAX_FILES) папка молча пропускается.

        Дерево тут же раскрывается к этой папке (асинхронно, уровень за
        уровнем — v0.7.6): раньше подсветка была привязана к результату
        скана (_scan_sync_tree), а восстановленный поиск по имени обгонял
        скан и сбрасывал его генератор — скан отбрасывался вместе с
        подсветкой, и после запуска с фильтром было не видно, где лежат
        картинки (репорт после обновления 0.7.4)."""
        last = QSettings("ImageHunter", "ImageHunter").value("viewer/last_folder", "")
        if not last:
            return
        self._scan_restore = True
        self._folder = last
        self._update_fav_button()
        self._gen += 1
        self._sync_tree_async(last)
        self._io_pool(last).start(
            _ScanTask(last, self._gen, self._scan_signals))

    @staticmethod
    def _is_under(path_n: str, base_n: str) -> bool:
        """path_n строго внутри base_n (учитывает корни дисков: «/», «C:\»)."""
        base = base_n if base_n.endswith(os.sep) else base_n + os.sep
        return path_n.startswith(base)

    def _sync_tree(self, folder: str) -> None:
        """Раскрывает в дереве путь к folder и подсвечивает её (для «Открыть папку…»)."""
        self._sync_seq += 1   # синхронная подсветка отменяет асинхронную прогулку
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
        self._populate_children_sync(item)
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

    # ---------- асинхронная прогулка по дереву к текущей папке ----------

    def _sync_tree_async(self, folder: str) -> None:
        """Раскрывает дерево к folder уровень за уровнем, не заминая интерфейс.

        Синхронный вариант (_sync_tree) на сетевом диске платит одним
        сетевым тайм-аутом за каждый уровень — здесь каждый уровень читает
        фоновый scandir (см. _populate_children), а когда подпапки готовы
        (_on_subdirs_ready), шаг повторяется для следующего уровня.
        Целевой путь хранится в самом узле (_TREE_SYNC_ROLE), поэтому
        перестройка дерева (refresh_drives) отменяет прогулку вместе с
        узлами. Запускается при восстановлении последней папки (в том
        числе когда активен восстановленный поиск — раньше этот случай
        оставлял дерево свёрнутым, v0.7.6).

        Новая прогулка (или синхронная подсветка, или клик по дереву)
        увеличивает _sync_seq: запоздалые шаги старой прогулки, видя
        чужое поколение, не трогают выделение."""
        self._sync_seq += 1
        seq = self._sync_seq
        folder_n = os.path.normpath(folder)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_n = os.path.normpath(top.data(0, Qt.ItemDataRole.UserRole) or "")
            if top_n == folder_n:
                self._sync_finish(top, seq)
                return
            if self._is_under(folder_n, top_n):
                self._sync_step(top, folder_n, seq)
                return

    def _sync_step(self, item: QTreeWidgetItem, folder_n: str, seq: int) -> None:
        """Один шаг прогулки: пометить узел целью, раскрыть и начать догрузку
        подпапок (если они ещё не читаются/не прочитаны)."""
        item.setData(0, _TREE_SYNC_ROLE, folder_n)
        item.setData(0, _TREE_SYNC_SEQ_ROLE, seq)
        if not item.data(0, Qt.ItemDataRole.UserRole + 1):
            self._populate_children(item)   # фоновый скан → продолжение в _on_subdirs_ready
        item.setExpanded(True)
        for i in range(item.childCount()):
            if item.child(i).data(0, Qt.ItemDataRole.UserRole):
                self._sync_continue(item)   # подпапки уже были прочитаны ранее
                return
        if item.childCount() == 0:
            self._sync_continue(item)       # папка уже прочитана и пуста
        # иначе — заглушка: скан в полёте, продолжим в _on_subdirs_ready

    def _sync_continue(self, item: QTreeWidgetItem) -> None:
        """Подпапки узла известны — найти следующее звено пути и спуститься."""
        folder_n = item.data(0, _TREE_SYNC_ROLE)
        seq = item.data(0, _TREE_SYNC_SEQ_ROLE)
        item.setData(0, _TREE_SYNC_ROLE, None)
        item.setData(0, _TREE_SYNC_SEQ_ROLE, 0)
        if not folder_n or seq != self._sync_seq:
            return   # прогулка отменена или узел без цели — выделение не трогаем
        for i in range(item.childCount()):
            child = item.child(i)
            child_n = os.path.normpath(child.data(0, Qt.ItemDataRole.UserRole) or "")
            if not child_n:
                continue                    # заглушка — не путь
            if child_n == folder_n:
                self._sync_finish(child, seq)
                return
            if self._is_under(folder_n, child_n):
                self._sync_step(child, folder_n, seq)
                return
        # дальше пути нет (папка удалена/недоступна) — подсветим ближайший узел
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def _sync_finish(self, item: QTreeWidgetItem, seq: int) -> None:
        """Цель достигнута: подсветить и показать найденную папку."""
        item.setData(0, _TREE_SYNC_ROLE, None)
        item.setData(0, _TREE_SYNC_SEQ_ROLE, 0)
        if seq != self._sync_seq:
            return   # пока шли, цель сменилась — выделение не трогаем
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    # ---------- служебное ----------

    def _on_thumb_ready(self, gen: int, row: int, img: QImage,
                        w: int = 0, h: int = 0) -> None:
        if gen != self._gen:
            return  # миниатюра из предыдущей папки — папка уже сменилась
        self._pending_thumbs[row] = img
        if w > 0 and h > 0:
            self._pending_dims[row] = _dims_text(w, h)
        if not self._thumb_timer.isActive():
            self._thumb_timer.start()

    def _flush_thumbs(self) -> None:
        with applog.timed(tr("perf.op.thumbs_batch"),
                          always=False, slow_ms=400) as t:
            pending, self._pending_thumbs = self._pending_thumbs, {}
            dims, self._pending_dims = self._pending_dims, {}
            for row, img in pending.items():
                item = self.list.item(row)
                if item is not None:
                    item.setIcon(QIcon(QPixmap.fromImage(img)))
                    res = dims.get(row)
                    if res:
                        # отдельная роль: текст плитки остаётся чистым именем
                        # файла — на нём завязаны rename/search/тесты
                        item.setData(_RES_ROLE, res)
            self._thumbs_done += len(pending)
            self._thumb_done_rows.update(pending.keys())
            self._thumb_timer.stop()
            t.set(rows=len(pending))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        # при первом показе вьюпорт получает реальные размеры — пора грузить видимые миниатюры
        self._schedule_visible_thumbs()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._mode == "fit" and not self._resize_mode:
            self._resize_timer.start()   # рескейл — после паузы в ресайзе (v0.7.11)
        self._schedule_visible_thumbs()

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
