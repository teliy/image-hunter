"""Многопоточный загрузчик изображений по прямым ссылкам.

Downloader — QObject, живущий в GUI-потоке. Каждое скачивание выполняется
в QThreadPool (до 6 потоков), прогресс и результат доставляются сигналами.
Статусы — канонические ключи ("ok"/"error"/"cancel"): текст на языке
интерфейса подбирается в слой отображения (downloads.py).
"""

from __future__ import annotations

import os
import re
import time
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Signal

from app.core import applog
from app.core.i18n import tr

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}
CONTENT_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
    "image/tiff": ".tif",
}
TIMEOUT = (10, 60)  # (подключение, чтение), секунды
MAX_THREADS = 6
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 МБ — страховка
KNOWN_IMAGE_EXTS = set(CONTENT_EXT.values()) | {".jfif", ".tif", ".tiff"}

# Статусы, при которых стоит попробовать запасные варианты заголовков/ссылки
RETRY_STATUSES = frozenset({401, 403, 429})

# Обёртка CDN Cloudflare: /cdn-cgi/image/<параметры>/<оригинал>
_CDN_WRAP_RE = re.compile(r"/cdn-cgi/image/[^/?&]+/(https?://.+)$", re.IGNORECASE)


def unwrap_cdn_url(url: str) -> str | None:
    """Раскрыть обёртку оптимизации CDN: /cdn-cgi/image/… → внутренний URL.

    Часть сайтов раздаёт картинки через Cloudflare Image Resizing; сама
    обёртка бывает закрыта от «чужих» (403), а внутренний оригинал — нет.
    """
    m = _CDN_WRAP_RE.search(url or "")
    inner = m.group(1) if m else ""
    return inner if inner.startswith(("http://", "https://")) else None


def fetch_image(url: str, referer: str | None = None) -> requests.Response:
    """Скачать картинку, перебирая запасные варианты при 401/403/429.

    Некоторые CDN (например, Cloudflare перед магазинами) отдают 403
    запросам без «правильного» Referer или на обёртку /cdn-cgi/image/.
    Лестница попыток:
    1. как есть (с присвоенным Referer страницы, если он был);
    2. без Referer — «жадные» CDN часто пускают «прямые» запросы;
    3. с Referer самого сайта картинки;
    4. раскрытая обёртка /cdn-cgi/image/ (с теми же вариантами Referer).
    Возвращает ответ с 2xx; исчерпав варианты, поднимает последнюю ошибку.
    """
    parts = urlparse(url or "")
    origin = f"{parts.scheme}://{parts.netloc}/" if parts.netloc else ""
    attempts: list[tuple[str, str | None]] = [(url, referer)]
    if referer:
        attempts.append((url, None))
    if origin and origin != referer:
        attempts.append((url, origin))
    inner = unwrap_cdn_url(url)
    if inner:
        attempts.append((inner, None))
        ip = urlparse(inner)
        if ip.netloc and f"{ip.scheme}://{ip.netloc}/" != origin:
            attempts.append((inner, f"{ip.scheme}://{ip.netloc}/"))

    last_exc: Exception | None = None
    last_resp: requests.Response | None = None
    for attempt_url, ref in attempts:
        headers = dict(BASE_HEADERS)
        if ref:
            headers["Referer"] = ref
        try:
            resp = requests.get(attempt_url, headers=headers,
                                timeout=TIMEOUT, stream=True)
        except Exception as exc:  # noqa: BLE001 — сеть моргнула, попробуем ещё
            last_exc, last_resp = exc, None
            continue
        if resp.status_code in RETRY_STATUSES and (attempt_url, ref) != attempts[-1]:
            last_exc, last_resp = None, resp
            resp.close()
            continue
        resp.raise_for_status()
        return resp
    if last_exc is not None:
        raise last_exc
    assert last_resp is not None  # все попытки кончились не-2xx статусом
    last_resp.raise_for_status()
    return last_resp


def sanitize_filename(name: str) -> str:
    """Оставить в имени файла только безопасные символы."""
    name = unquote(name or "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:150]


def filename_from_url(url: str, content_type: str) -> str:
    """Сформировать имя файла по URL и Content-Type ответа."""
    path = urlparse(url).path
    base = os.path.basename(path)
    stem, ext = os.path.splitext(sanitize_filename(base))
    if not ext or ext.lower() not in KNOWN_IMAGE_EXTS:
        ext = CONTENT_EXT.get(content_type, ext or ".jpg")
    if not stem:
        stem = f"image_{time.strftime('%Y%m%d_%H%M%S')}"
    return f"{stem}{ext}"


def unique_path(directory: str, filename: str) -> str:
    """Вернуть путь, не совпадающий с уже существующими файлами."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}-{counter}{ext}")
        counter += 1
    return candidate


class _DownloadTask(QRunnable):
    """Одно скачивание. Результаты отдаёт сигналами владельца (Downloader)."""

    def __init__(self, owner: "Downloader", row_id: int, url: str,
                 referer: str | None, directory: str):
        super().__init__()
        self.owner = owner
        self.row_id = row_id
        self.url = url
        self.referer = referer
        self.directory = directory

    def run(self) -> None:  # выполняется в рабочем потоке
        t0 = time.perf_counter()
        if self.owner.is_stopped():
            self.owner.status_changed.emit(self.row_id, "cancel", "")
            self.owner._task_done(False)
            return
        try:
            resp = fetch_image(self.url, self.referer)
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type and not content_type.startswith("image/"):
                raise ValueError(f"не изображение ({content_type})")
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > MAX_FILE_SIZE:
                raise ValueError("файл слишком большой (>100 МБ)")

            # имя — по фактическому адресу ответа: после запасной попытки
            # (раскрытая обёртка CDN) это уже настоящий адрес файла
            fname = filename_from_url(resp.url or self.url, content_type)
            path = unique_path(self.directory, fname)
            received = 0
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if self.owner.is_stopped():
                        fh.close()
                        os.remove(path)
                        raise ValueError("отменено пользователем")
                    received += len(chunk)
                    if received > MAX_FILE_SIZE:
                        raise ValueError("файл слишком большой (>100 МБ)")
                    fh.write(chunk)
            applog.event("log.event.timing",
                         op=tr("perf.op.download", name=os.path.basename(path)),
                         ms=round((time.perf_counter() - t0) * 1000),
                         extra=applog.extra(kb=received // 1024))
            self.owner.status_changed.emit(self.row_id, "ok", path)
            self.owner._task_done(True)
        except Exception as exc:  # noqa: BLE001 — показываем текст ошибки в таблице
            # долгая неудача тоже важна: видно, сколько время ушло до ошибки
            applog.event("log.event.timing",
                         op=tr("perf.op.download", name=self.url.rsplit("/", 1)[-1][:60]),
                         ms=round((time.perf_counter() - t0) * 1000),
                         extra=applog.extra(error=type(exc).__name__))
            self.owner.status_changed.emit(self.row_id, "error", str(exc)[:200])
            self.owner._task_done(False)


class Downloader(QObject):
    """Очередь скачиваний с дедупликацией ссылок внутри сессии."""

    status_changed = Signal(int, str, str)          # row_id, статус, путь/ошибка
    batch_finished = Signal(int, int)               # успешно, с ошибками

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_THREADS)
        self._seen: set[str] = set()
        self._row_id = 0
        self._stopped = False
        self._pending = 0
        self._ok = 0
        self._fail = 0
        self._batch_t0 = 0.0

    # ---------- публичный API (GUI-поток) ----------

    def add(self, urls) -> list[tuple[int, str]]:
        """Добавить ссылки, вернув только новые: [(row_id, url), ...]."""
        fresh: list[tuple[int, str]] = []
        for raw in urls:
            url = (raw or "").strip()
            if not url or not url.startswith(("http://", "https://")):
                continue
            if url in self._seen:
                continue
            self._seen.add(url)
            self._row_id += 1
            fresh.append((self._row_id, url))
        return fresh

    def start(self, items: list[tuple[int, str]], referer: str | None, directory: str) -> None:
        """Поставить новые задачи в очередь и начать скачивание."""
        if not items:
            return
        os.makedirs(directory, exist_ok=True)
        self._stopped = False
        self._ok = 0
        self._fail = 0
        self._pending = len(items)
        self._batch_t0 = time.perf_counter()   # для тайминга пачки в журнале
        for row_id, url in items:
            self._pool.start(_DownloadTask(self, row_id, url, referer, directory))

    def stop(self) -> None:
        """Остановить запуск новых задач; уже идущие докачаются или отменятся."""
        self._stopped = True

    def is_stopped(self) -> bool:
        return self._stopped

    def reset_seen(self) -> None:
        """Разрешить повторное скачивание тех же ссылок (кнопка «Сбросить дубли»)."""
        self._seen.clear()

    # ---------- внутреннее (вызывается из рабочих потоков) ----------

    def _task_done(self, ok: bool) -> None:
        # += под GIL атомарен, гонки не критичны: каждая задача вызывается один раз
        if ok:
            self._ok += 1
        else:
            self._fail += 1
        self._pending -= 1
        if self._pending <= 0:
            # тайминг пачки: сколько длилось скачивание всего (в т.ч. по вине сети)
            applog.event("log.event.timing", op=tr("perf.op.download_batch"),
                         ms=round((time.perf_counter() - self._batch_t0) * 1000),
                         extra=applog.extra(ok=self._ok, fail=self._fail))
            self.batch_finished.emit(self._ok, self._fail)


def default_download_dir() -> str:
    """Папка по умолчанию: «Изображения/ImageHunter» (или ~/Pictures/ImageHunter)."""
    from PySide6.QtCore import QStandardPaths

    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    if not pictures:
        pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    return os.path.join(pictures, "ImageHunter")


def saved_download_dir() -> str:
    settings = QSettings("ImageHunter", "ImageHunter")
    directory = str(settings.value("download_dir", "") or "")
    return directory if directory else default_download_dir()


def store_download_dir(directory: str) -> None:
    QSettings("ImageHunter", "ImageHunter").setValue("download_dir", directory)
