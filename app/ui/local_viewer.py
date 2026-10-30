"""Вкладка «Мои картинки»: дерево дисков/папок + миниатюры + полноэкранный просмотр с зумом."""

from __future__ import annotations

import hashlib
import os
import random
import re
import tempfile
import time

from PySide6.QtCore import (
    QEvent,
    QObject,
    QMimeData,
    QPoint,
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
    QDesktopServices,
    QDrag,
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
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
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

from app.core import applog, i18n
from app.core.i18n import tr

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
THUMB = 160
TREE_WIDTH = 230
THUMB_CACHE_MAX = 256 * 1024 * 1024   # предел кэша миниатюр на диске

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


# ---------- фоновые миниатюры с постоянным кэшем на диске ----------

class _ThumbSignals(QObject):
    ready = Signal(int, int, QImage)  # поколение папки, строка списка, готовая миниатюра


def _thumb_cache_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    d = os.path.join(base or tempfile.gettempdir(), "ImageHunter", "thumbs")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return ""


def _thumb_cache_key(path: str, size: int, mtime: float) -> str:
    # путь + размер + mtime: ключ меняется, когда файл перезаписан
    try:
        norm = os.path.normcase(os.path.abspath(path))
    except OSError:
        norm = path
    raw = f"{norm}|{size}|{mtime:.0f}".encode("utf-8", "surrogateescape")
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
        cache_path = ""
        if self.cache_dir:
            key = _thumb_cache_key(self.path, self.size, self.mtime)
            cache_path = os.path.join(self.cache_dir, key + ".png")
            cached = QImage(cache_path)
            if not cached.isNull():
                self.signals.ready.emit(self.gen, self.row, cached)
                return
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            reader.setScaledSize(size.scaled(THUMB, THUMB, Qt.KeepAspectRatio))
        img = reader.read()
        if img.isNull():
            return
        if cache_path:
            self._store(cache_path, img)
        self.signals.ready.emit(self.gen, self.row, img)

    def _store(self, cache_path: str, img: QImage) -> None:
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
    порциями, не дожидаясь конца обхода."""

    MAX_RESULTS = 5000    # предел выдачи
    MAX_FOLDERS = 20000   # предел обхода (страховка от гигантских деревьев)
    BATCH = 50

    def __init__(self, base: str, needle: str, gen: int,
                 signals: _SearchSignals, handle: _SearchHandle):
        super().__init__()
        self.base, self.needle = base, needle
        self.gen, self.signals, self.handle = gen, signals, handle

    def run(self) -> None:
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
                                  and self.needle in name.lower()):
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


# ---------- фоновый поиск папок для дерева «Диски и папки» ----------

class _FolderSearchSignals(QObject):
    batch = Signal(int, list)            # поколение поиска, порция [путь]
    done = Signal(int, int, bool)        # поколение, всего найдено, усечено ли


class _FolderSearchTask(QRunnable):
    """Рекурсивный поиск папок по имени от корней дерева (Домой, Изображения,
    все диски). Один os.scandir на папку, без stat() на каждый элемент —
    важно для сетевых дисков. Совпадения отдаются порциями, не дожидаясь
    конца обхода. Симлинки не разворачиваются (нет циклов), скрытые папки
    пропускаются. Пределы количества/времени страхуют от гигантских деревьев
    и медленных носителей: поиск всегда завершается сам."""

    MAX_RESULTS = 400        # предел выдачи
    MAX_DIRS = 150_000       # предел обхода
    TIME_BUDGET = 12.0       # секунд — страховка от очень медленных дисков
    MAX_DEPTH = 40           # защита от аномально глубоких деревьев
    BATCH = 30

    def __init__(self, roots: list[str], needle: str, gen: int,
                 signals: _FolderSearchSignals, handle: _SearchHandle):
        super().__init__()
        self.roots = list(roots)
        self.needle = needle.lower()
        self.gen, self.signals, self.handle = gen, signals, handle

    def run(self) -> None:
        found = 0
        pending: list[str] = []
        truncated = False
        scanned = 0
        seen: set[str] = set()   # уже просмотренные папки — корни могут пересекаться
        deadline = time.monotonic() + self.TIME_BUDGET
        stack: list[tuple[str, int]] = [(path, 0) for path in reversed(self.roots)]
        while stack:
            if self.handle.cancelled:
                return
            if (found >= self.MAX_RESULTS or scanned >= self.MAX_DIRS
                    or time.monotonic() > deadline):
                truncated = True
                break
            path, depth = stack.pop()
            key = os.path.normcase(os.path.normpath(path))
            if key in seen:
                continue
            seen.add(key)
            scanned += 1
            subdirs: list[str] = []
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.name.startswith(".") or _is_hidden_entry(entry):
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                subdirs.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
            subdirs.sort(key=lambda p: natural_key(os.path.basename(p)))
            for sub in subdirs:
                if self.needle in os.path.basename(sub).lower():
                    found += 1
                    pending.append(sub)
            if depth < self.MAX_DEPTH:
                stack.extend((sub, depth + 1) for sub in reversed(subdirs))
            if len(pending) >= self.BATCH:
                self.signals.batch.emit(self.gen, pending)
                pending = []
        if self.handle.cancelled:
            return
        if pending:
            self.signals.batch.emit(self.gen, pending)
        self.signals.done.emit(self.gen, found, truncated)


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
        self._fs_gen = 0                 # поколение поиска папок в дереве
        self._fs_handle = None           # флажок отмены текущего поиска папок
        self._fs_count = 0               # сколько папок показано
        self._fs_seen: set[str] = set()  # normpath уже показанных совпадений
        self._fs_in_search = False       # дерево сейчас показывает результаты поиска папок

        # --- верхняя панель ---
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)

        # (кнопка, ключ_текста | None, ключ_подсказки) — для перетрансляции при смене языка
        self._i18n_buttons: list[tuple[QToolButton, str | None, str]] = []

        def btn(text_key: str | None, tip_key: str, slot, shortcut=None,
                literal: str | None = None) -> QToolButton:
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
            bar.addWidget(b)
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
        btn("viewer.reveal", "viewer.reveal_tip", self.reveal_folder)
        bar.addSpacing(8)
        self.search_edit = _GripEdit("viewer/search_width", default_w=220)
        self.search_edit.setPlaceholderText(tr("viewer.search_ph"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(tr("viewer.search_tip"))
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.returnPressed.connect(self._start_search_now)
        bar.addWidget(self.search_edit)
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.activated.connect(self._escape_search)   # Esc чистит то поле, где фокус
        bar.addStretch(1)
        self.status = QLabel(tr("viewer.pick"))
        self.status.setStyleSheet("color: #666;")
        bar.addWidget(self.status)

        # --- список миниатюр ---
        self.list = _ThumbList()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setMinimumWidth(THUMB + 34)  # ширина задаётся сплиттером — панель растягивается мышью
        # drag'n'drop: выделенные файлы перетаскиваются мышью в другие приложения
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragOnly)
        self.list.setToolTip(tr("viewer.dnd_tip"))
        # запасной перенос без драга: Ctrl+C или правый клик — файлы в буфер обмена
        sc_copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.list)
        sc_copy.activated.connect(self.copy_selected_files)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_context_menu)
        self.list.currentRowChanged.connect(self._show_index)
        self.list.itemDoubleClicked.connect(
            lambda item: QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
        )
        # прокрутили список — надо догрузить миниатюры новых видимых строк
        self.list.verticalScrollBar().valueChanged.connect(self._schedule_visible_thumbs)

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
        self.tree_hdr_label = QLabel(tr("viewer.drives"))
        tree_hdr.addWidget(self.tree_hdr_label)
        tree_hdr.addStretch(1)
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
        # поиск папок в дереве: сигналы + дебаунс набора (300 мс)
        self._fs_signals = _FolderSearchSignals()
        self._fs_signals.batch.connect(self._on_fs_batch)
        self._fs_signals.done.connect(self._on_fs_done)
        self._fs_timer = QTimer(self)
        self._fs_timer.setSingleShot(True)
        self._fs_timer.setInterval(300)
        self._fs_timer.timeout.connect(self._start_folder_search_now)
        # ленивые миниатюры: пересчёт видимых строк не чаще раза в 120 мс
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(120)
        self._visible_timer.timeout.connect(self._queue_visible_thumbs)

        self.refresh_drives()
        self._restore_last_folder()
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
        self.folder_search.setPlaceholderText(tr("viewer.folders_search_ph"))
        self.folder_search.setToolTip(tr("viewer.folders_search_tip"))
        self.list.setToolTip(tr("viewer.dnd_tip"))
        self.tree_hdr_label.setText(tr("viewer.drives"))
        if not self._paths:
            self.status.setText(tr("viewer.pick"))
        if self._fs_in_search:
            # режим поиска папок: дерево не перечитываем — не затирать результаты
            if self._fs_handle is not None:
                self.tree_info.setText(tr("viewer.folders_searching_found", n=self._fs_count))
            elif self._fs_count:
                self.tree_info.setText(tr("viewer.folders_found", n=self._fs_count))
            else:
                self.tree_info.setText(tr("viewer.folders_none"))
        else:
            # быстрые ссылки «Домой»/«Изображения» тоже переводятся
            self.refresh_drives()

    # ---------- публичное ----------

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("viewer.open_dlg"), self._folder or "")
        if folder:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
            self._cancel_search()
            self.load_folder(folder, sync_tree=True)

    def current_folder(self) -> str:
        """Папка, открытая сейчас во вкладке (используется для сохранения WebP)."""
        return self._folder

    def refresh(self) -> None:
        """Пересканировать текущую папку (например, после сохранения в неё WebP)."""
        if self._folder and os.path.isdir(self._folder):
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

    def _list_context_menu(self, pos) -> None:
        """Правый клик на ленте: открыть / копировать выделенные файлы."""
        menu = QMenu(self)
        act_open = menu.addAction(tr("viewer.ctx_open"))
        act_copy = menu.addAction(tr("viewer.ctx_copy"))
        act_copy.setToolTip(tr("viewer.ctx_copy_tip"))
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is act_open:
            item = self.list.currentItem()
            if item is not None and item.data(Qt.UserRole):
                QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))
        elif chosen is act_copy:
            self.copy_selected_files()

    def load_folder(self, folder: str, entries: list[tuple[str, int, float]] | None = None,
                    sync_tree: bool = False) -> None:
        self._cancel_search()
        self._folder = folder
        if entries is None:
            entries = scan_image_entries(folder)
        self._gen += 1
        self._pool.clear()   # не начатые миниатюры прошлой папки больше не нужны
        self._paths = [p for p, _s, _m in entries]
        self._meta = [(s, m) for _p, s, m in entries]
        applog.event("log.event.folder", folder=folder, n=len(self._paths))
        self.list.clear()
        self._pending_thumbs.clear()
        self._thumb_queued.clear()
        self._thumb_done_rows.clear()
        self._thumbs_done = 0
        self._pixmap = None
        self._movie = None

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
            self.list.setCurrentRow(0)
        else:
            self.view_label.setText(tr("viewer.no_images"))
            self.status.setText(folder or "—")
        self._schedule_visible_thumbs()

        QSettings("ImageHunter", "ImageHunter").setValue("viewer/last_folder", folder)
        if sync_tree:
            self._sync_tree(folder)

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
        self._thumb_queued.clear()
        self._thumb_done_rows.clear()
        self._thumbs_done = 0
        self._pixmap = None
        self._movie = None
        self.status.setText(tr("viewer.searching", q=needle))
        QThreadPool.globalInstance().start(
            _SearchTask(base, needle.lower(), self._gen, self._search_signals, handle))

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

    # ---------- поиск папок в дереве «Диски и папки» ----------

    def _escape_search(self) -> None:
        """Esc чистит то поле поиска, где сейчас фокус."""
        if QApplication.focusWidget() is self.folder_search:
            self.folder_search.clear()
        else:
            self.search_edit.clear()

    def _on_folder_search_text_changed(self, text: str) -> None:
        if not text.strip():
            self._cancel_folder_search()
            self._exit_folder_search_mode()
            return
        self._fs_timer.start()   # дебаунс: не запускаем обход на каждое нажатие

    def _cancel_folder_search(self) -> None:
        self._fs_timer.stop()
        if self._fs_handle is not None:
            self._fs_handle.cancelled = True
            self._fs_handle = None

    def _on_tree_refresh_clicked(self) -> None:
        if self.folder_search.text():
            self.folder_search.clear()   # выйдет из режима поиска и перерисует дерево
        if not self._fs_in_search:
            self.refresh_drives()

    def _search_roots(self) -> list[str]:
        """Корни для поиска папок: те же, что показывает дерево
        (Домой, Изображения и все не-виртуальные смонтированные диски)."""
        roots: list[str] = []
        home = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)
        pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        if home and os.path.isdir(home):
            roots.append(home)
        if pics and os.path.isdir(pics) and os.path.normpath(pics) != os.path.normpath(home):
            roots.append(pics)
        for si in QStorageInfo.mountedVolumes():
            if not si.isValid() or not si.isReady() or self._is_virtual(si):
                continue
            root = si.rootPath()
            if root and os.path.isdir(root):
                roots.append(root)
        uniq: list[str] = []
        seen: set[str] = set()
        for root in roots:
            key = os.path.normcase(os.path.normpath(root))
            if key not in seen:
                seen.add(key)
                uniq.append(root)
        return uniq

    def _start_folder_search_now(self) -> None:
        self._fs_timer.stop()
        needle = self.folder_search.text().strip()
        if not needle:
            return
        self._cancel_folder_search()
        handle = _SearchHandle()
        self._fs_handle = handle
        self._fs_gen += 1
        self._fs_count = 0
        self._fs_seen = set()
        self._fs_in_search = True
        self.tree.clear()
        self.tree.setColumnCount(2)
        self.tree.setColumnWidth(0, 120)
        self.tree_info.show()
        self.tree_info.setText(tr("viewer.folders_searching"))
        applog.event("log.event.folder_search", q=needle)
        QThreadPool.globalInstance().start(
            _FolderSearchTask(self._search_roots(), needle, self._fs_gen,
                              self._fs_signals, handle))

    def _add_folder_result(self, path: str) -> None:
        key = os.path.normcase(os.path.normpath(path))
        if key in self._fs_seen:
            return
        self._fs_seen.add(key)
        name = os.path.basename(path) or path
        item = QTreeWidgetItem([name, os.path.dirname(path)])   # имя + путь родителя серым
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        item.setToolTip(0, path)
        item.setToolTip(1, path)
        item.setForeground(1, self.palette().brush(QPalette.ColorRole.PlaceholderText))
        item.addChild(self._dummy_item())   # результат можно раскрыть прямо в дереве
        self.tree.addTopLevelItem(item)

    def _on_fs_batch(self, gen: int, items: list) -> None:
        if gen != self._fs_gen or not self._fs_in_search:
            return
        for path in items:
            self._add_folder_result(path)
        self._fs_count = len(self._fs_seen)
        self.tree_info.setText(tr("viewer.folders_searching_found", n=self._fs_count))
        if self.tree.currentItem() is None and self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _on_fs_done(self, gen: int, total: int, truncated: bool) -> None:
        if gen != self._fs_gen or not self._fs_in_search:
            return
        self._fs_handle = None
        self._fs_count = len(self._fs_seen)
        if not self._fs_count:
            self.tree_info.setText(tr("viewer.folders_none"))
            return
        tail = tr("viewer.folders_trunc", n=total) if truncated else ""
        self.tree_info.setText(tr("viewer.folders_found", n=self._fs_count) + tail)
        applog.event("log.event.folder_search_done",
                     q=self.folder_search.text().strip(), n=self._fs_count)

    def _open_first_folder_result(self) -> None:
        """Enter в поле поиска папок — открыть первую (или выделенную) находку."""
        if not self._fs_in_search:
            return
        item = self.tree.currentItem() or self.tree.topLevelItem(0)
        if item is not None:
            self._on_tree_clicked(item, 0)

    def _exit_folder_search_mode(self) -> None:
        """Вернуть обычное дерево: корни + текущая папка раскрыта и подсвечена."""
        if not self._fs_in_search:
            return
        self._fs_in_search = False
        self.tree.clear()
        self.tree.setColumnCount(1)
        self.tree_info.hide()
        self.refresh_drives()
        if self._folder and os.path.isdir(self._folder):
            self._sync_tree(self._folder)

    # ---------- ленивые миниатюры: грузим только видимую часть ----------

    def _on_toggle_thumbs(self, checked: bool) -> None:
        """Выключатель предпросмотра; состояние запоминается между запусками."""
        QSettings("ImageHunter", "ImageHunter").setValue("viewer/thumbs", checked)
        self._thumbs_enabled = checked
        if checked:
            self._schedule_visible_thumbs()
        else:
            self._pool.clear()            # не начатые задачи больше не нужны
            self._pending_thumbs.clear()
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
            self._pool.start(_ThumbTask(self._paths[row], row, self._gen,
                                        self._thumb_signals, cache_dir, size, mtime))

    # ---------- просмотр ----------

    def step(self, delta: int) -> None:
        if not self._paths:
            return
        row = (self.list.currentRow() + delta) % self.list.count()
        self.list.setCurrentRow(row)

    def _show_index(self, row: int) -> None:
        if not (0 <= row < len(self._paths)):
            return
        # файл может читаться по сети — показываем занятость,
        # чтобы клики не «висли» молча
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            self._load_view(self._paths[row], row)
        finally:
            QApplication.restoreOverrideCursor()

    def _load_view(self, path: str, row: int) -> None:
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
                self.view_label.setText(tr("viewer.cant_open", err=img.errorString()))
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
            f"{os.path.basename(path)}  •  {tr('viewer.of', i=row + 1, n=len(self._paths))}"
            f"  •  {size.width()}×{size.height()}"
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
            self._add_folder_item(None, home, title=tr("viewer.home"),
                                  icon=QStyle.StandardPixmap.SP_DirHomeIcon)
        if pics and os.path.isdir(pics) and os.path.normpath(pics) != os.path.normpath(home):
            self._add_folder_item(None, pics, title=tr("viewer.pictures"))

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
            label = "💾 " + (path if len(path) > 1 else tr("viewer.drive_root"))
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        total, free = si.bytesTotal(), si.bytesFree()
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

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._populate_children(item)
        item.setExpanded(True)
        self._folder = path
        if self.search_edit.text().strip():
            self._start_search_now()   # поиск от заново выбранной папки
        else:
            self.load_folder(path)

    def _restore_last_folder(self) -> None:
        last = QSettings("ImageHunter", "ImageHunter").value("viewer/last_folder", "")
        if not (last and os.path.isdir(last)):
            return
        # авто-открытие только для папок разумного размера, чтобы не тормозить запуск
        entries = scan_image_entries(last)
        if 0 < len(entries) <= 2000:
            self.load_folder(last, entries=entries, sync_tree=True)

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

    def _on_thumb_ready(self, gen: int, row: int, img: QImage) -> None:
        if gen != self._gen:
            return  # миниатюра из предыдущей папки — папка уже сменилась
        self._pending_thumbs[row] = img
        if not self._thumb_timer.isActive():
            self._thumb_timer.start()

    def _flush_thumbs(self) -> None:
        pending, self._pending_thumbs = self._pending_thumbs, {}
        for row, img in pending.items():
            item = self.list.item(row)
            if item is not None:
                item.setIcon(QIcon(QPixmap.fromImage(img)))
        self._thumbs_done += len(pending)
        self._thumb_done_rows.update(pending.keys())
        self._thumb_timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        # при первом показе вьюпорт получает реальные размеры — пора грузить видимые миниатюры
        self._schedule_visible_thumbs()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._mode == "fit":
            self._apply_mode()
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
