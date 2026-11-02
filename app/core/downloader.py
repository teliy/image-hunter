"""Многопоточный загрузчик изображений по прямым ссылкам.

Downloader — QObject, живущий в GUI-потоке. Каждое скачивание выполняется
в QThreadPool (до 6 потоков), прогресс и результат доставляются сигналами.
Статусы — канонические ключи ("ok"/"error"/"cancel"): текст на языке
интерфейса подбирается в слой отображения (downloads.py).
"""

from __future__ import annotations

import os
import re
import threading
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

# сессия requests, закреплённая за рабочим потоком (см. _http_get)
_TLS = threading.local()


def _http_get():
    """Функция запроса с сессией на поток — переиспользование TCP/TLS.

    Каждый requests.get() открывает новое соединение: пачка из сотни картинок
    с одного CDN платит рукопожатие TLS за каждую, а сокеты копятся в
    TIME_WAIT. Сессия, закреплённая за рабочим потоком (их у загрузчика
    максимум 6 + 3 у сохранения), переиспользует соединения через пул
    urllib3 (v0.7.11). Если requests подменён тестами (объект без Session) —
    честный запасной путь через requests.get.
    """
    if getattr(requests, "__name__", "") != "requests":
        return requests.get   # подмена requests в тестах — без сессии
    session = getattr(_TLS, "session", None)
    if session is None:
        session = requests.Session()
        _TLS.session = session
    return session.get


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
    http_get = _http_get()
    for attempt_url, ref in attempts:
        headers = dict(BASE_HEADERS)
        if ref:
            headers["Referer"] = ref
        try:
            resp = http_get(attempt_url, headers=headers,
                            timeout=TIMEOUT, stream=True)
        except Exception as exc:  # noqa: BLE001 — сеть моргнула, попробуем ещё
            last_exc, last_resp = exc, None
            continue
        if resp.status_code in RETRY_STATUSES and (attempt_url, ref) != attempts[-1]:
            last_exc, last_resp = None, resp
            resp.close()
            continue
        try:
            resp.raise_for_status()
        except Exception:
            resp.close()   # неудачный ответ не держит соединение до GC (v0.7.11)
            raise
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
    """Вернуть путь, не совпадающий с уже существующими файлами.

    Запись идёт через _create_exclusive — эта функция осталась для
    справочных целей (показать пользователю, куда сохранится файл)."""
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}-{counter}{ext}")
        counter += 1
    return candidate


def _create_exclusive(directory: str, filename: str) -> tuple[int, str]:
    """Создать файл записи с атомарно-свободным именем (O_CREAT|O_EXCL).

    Классический «os.path.exists → open» гонок не видит: шесть параллельных
    скачиваний, у которых совпало имя (image.jpg с разных ссылок), получали
    один и тот же путь, и один файл затирал другой. Эксклюзивное создание
    атомарно средствами ОС: проигравший поток честно берёт следующий
    свободный номер (image-1.jpg, image-2.jpg…) — ничего не пропадает
    (v0.7.11).
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    stem, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while True:
        try:
            return os.open(candidate, flags, 0o644), candidate
        except FileExistsError:
            candidate = os.path.join(directory, f"{stem}-{counter}{ext}")
            counter += 1


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
            fd, path = _create_exclusive(self.directory, fname)
            received = 0
            with os.fdopen(fd, "wb") as fh:
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
