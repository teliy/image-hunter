"""Перекодирование отмеченных картинок в WebP и сохранение в папку просмотра.

Отмеченные галочками плитки выдачи скачиваются в память (requests, как в
Downloader), декодируются Qt — QImage можно использовать в рабочих потоках,
QImageReader с AutoTransform разворачивает фото по EXIF — и записываются
как WebP в папку, открытую во вкладке «Мои картинки».

Правила имён: название.webp, название-1.webp, название-2.webp и так далее;
если имя занято существующим файлом папки, счётчик просто продолжается.
"""

from __future__ import annotations

import os
import re

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

from app.core.downloader import BASE_HEADERS, MAX_FILE_SIZE, TIMEOUT

WEBP_QUALITY = 90          # качество перекодирования (0–100)
MAX_THREADS = 3            # пощада к медленным источникам

# символы, запрещённые в именах файлов Windows
_FORBIDDEN = '<>:"/\\|?*'


def sanitize_base_name(name: str) -> str:
    """«Мой кот: 2024?» → «Мой кот 2024» — имя, пригодное для файла."""
    name = (name or "").strip()
    name = "".join(ch for ch in name if ch not in _FORBIDDEN)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120]


def _existing_lower_names(folder: str) -> set[str]:
    """Имена файлов папки в нижнем регистре (одно os.listdir на пачку)."""
    try:
        return {n.lower() for n in os.listdir(folder)}
    except OSError:
        return set()


def next_webp_name(folder: str, base: str, used: set[str],
                   existing_lower: set[str] | None = None) -> str:
    """Первое свободное имя: base.webp, затем base-1.webp, base-2.webp…

    Учитывает и уже существующие файлы папки (сравнение без регистра —
    как на дисках Windows), и имена, выданные в текущей пачке.
    """
    if existing_lower is None:
        existing_lower = _existing_lower_names(folder)
    lower_used = {u.lower() for u in used}
    candidate = f"{base}.webp"
    n = 0
    while (candidate.lower() in lower_used
           or candidate.lower() in existing_lower):
        n += 1
        candidate = f"{base}-{n}.webp"
    used.add(candidate)
    return candidate


def assign_webp_names(folder: str, base: str, count: int) -> list[str]:
    """Имена для всей пачки заранее: порядок совпадёт с порядком отметок."""
    existing_lower = _existing_lower_names(folder)
    used: set[str] = set()
    return [next_webp_name(folder, base, used, existing_lower) for _ in range(count)]


def decode_to_webp(data: bytes, out_path: str, quality: int = WEBP_QUALITY) -> tuple[int, int]:
    """Декодировать присланные байты (любой формат Qt) и записать WebP.

    Возвращает (ширина, высота). QImageReader с AutoTransform применяет
    EXIF-поворот — фото из телефонов сохраняются «головой вверх».
    """
    from PySide6.QtCore import QBuffer, QByteArray

    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QBuffer.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    img = reader.read()
    if img.isNull():
        raise ValueError(f"не удалось декодировать ({img.errorString()})")
    if not img.save(out_path, "WEBP", quality):
        raise ValueError("не удалось записать WebP")
    return img.width(), img.height()


class _WebpTask(QRunnable):
    """Скачивание одного оригинала в память + запись WebP под готовое имя."""

    def __init__(self, owner: "WebpSaver", index: int, url: str, filename: str,
                 folder: str, referer: str | None):
        super().__init__()
        self.owner = owner
        self.index = index
        self.url = url
        self.filename = filename
        self.folder = folder
        self.referer = referer

    def run(self) -> None:  # рабочий поток
        if self.owner.is_stopped():
            self.owner._task_done(self.index, False, "отменено")
            return
        headers = dict(BASE_HEADERS)
        if self.referer:
            headers["Referer"] = self.referer
        try:
            resp = requests.get(self.url, headers=headers, timeout=TIMEOUT, stream=True)
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith("image/"):
                raise ValueError(f"не изображение ({ctype})")
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if self.owner.is_stopped():
                    raise ValueError("отменено пользователем")
                buf.extend(chunk)
                if len(buf) > MAX_FILE_SIZE:
                    raise ValueError("файл слишком большой (>100 МБ)")
            if not buf:
                raise ValueError("пустой ответ")
            size = decode_to_webp(bytes(buf), os.path.join(self.folder, self.filename))
            self.owner._task_done(self.index, True,
                                  f"{self.filename} ({size[0]}×{size[1]})")
        except Exception as exc:  # noqa: BLE001 — текст ошибки уходит в статус
            self.owner._task_done(self.index, False, str(exc)[:200])


class WebpSaver(QObject):
    """Пачка (url, имя файла) → WebP в папку. Прогресс и итог — сигналами."""

    file_done = Signal(int, bool, str)   # индекс, успех, «имя (Ш×В)» или ошибка
    finished = Signal(int, int, str)     # сохранено, ошибок, папка

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_THREADS)
        self._stopped = False
        self._pending = 0
        self._ok = 0
        self._fail = 0
        self._folder = ""

    def start(self, jobs: list[tuple[str, str]], referer: str | None, folder: str) -> None:
        """jobs: [(url, имя_файла)] — имена уже выданы assign_webp_names()."""
        if not jobs:
            return
        os.makedirs(folder, exist_ok=True)
        self._stopped = False
        self._folder = folder
        self._pending = len(jobs)
        self._ok = 0
        self._fail = 0
        for index, (url, filename) in enumerate(jobs):
            self._pool.start(_WebpTask(self, index, url, filename, folder, referer))

    def stop(self) -> None:
        self._stopped = True

    def is_stopped(self) -> bool:
        return self._stopped

    def is_busy(self) -> bool:
        return self._pending > 0

    # ---------- внутреннее (вызывается из рабочих потоков) ----------

    def _task_done(self, index: int, ok: bool, info: str) -> None:
        if ok:
            self._ok += 1
        else:
            self._fail += 1
        self.file_done.emit(index, ok, info)
        self._pending -= 1
        if self._pending <= 0:
            self.finished.emit(self._ok, self._fail, self._folder)
