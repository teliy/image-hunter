"""Поиск картинок в интернете для веб-сервера — без встроенного браузера.

Во вкладке «Поиск картинок» выдача открывается во встроенном браузере
(QWebEngineView — целый Chromium), а ссылки собирает JavaScript на странице
(``app/core/extractor.py``). Серверу — живущему в потоке программы или
headless-процессом — такой путь не подходит: там нет ни Qt-виджетов, ни JS.
Поэтому сервер сам ходит по адресам, которые отдают данные в чистом виде:

* DuckDuckGo — JSON-выдача ``i.js``: тот же адрес, откуда страница выдачи
  берёт очередную пачку плиток при прокрутке; перед первым запросом со
  страницы выдачи снимается токен ``vqd``;
* Bing — серверная HTML-выдача: у каждой плитки в атрибуте ``m=`` лежит
  JSON со ссылкой на оригинал (``murl``), миниатюру (``turl``), заголовком
  и размерами.

Формат результата общий для всех движков и повторяет то, что показывают
плитки в программе: ``url`` (оригинал), ``thumb`` (миниатюра), ``title``,
``w``/``h`` (размеры, если выдача их отдала), ``source`` (страница-источник).

Скачивание картинок — по тем же правилам, что у программы
(``app/core/downloader.py``): лестница попыток с Referer (часть CDN пускает
только «свои» запросы), раскрытие обёртки Cloudflare ``/cdn-cgi/image/``,
имя файла из адреса ответа с подменой расширения по Content-Type,
атомарно-свободное имя (``name-1.ext``) при совпадении. Чистые правила
скопированы, а не импортированы: пакет ``app/server`` не тянет за собой
PySide6, чтобы работать даже там, где интерфейс не установлен.

Адреса движков (``DDG_BASE``, ``DDG_IJS``, ``BING_URL``) — константы уровня
модуля: тесты подменяют их на локальный мок-сервер и проверяют разбор выдачи
без сети. Все ошибки — :class:`WebSearchError` с честным текстом: HTTP-слой
превращает её в ответ 502, фоновой загрузчик — в строку ошибки задания.
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import threading
import time
from urllib.parse import quote_plus, urlparse

import requests


class WebSearchError(Exception):
    """Поисковик или сайт с картинкой не ответил / ответил не тем, что ждём."""


# ---------------------------------------------------------------- адреса
# уровня модуля — тесты подменяют на мок-сервер (см. scripts/test_server.py)

DDG_BASE = "https://duckduckgo.com"           # страница выдачи, из неё берём vqd
DDG_IJS = "https://duckduckgo.com/i.js"       # JSON-выдача картинок
BING_URL = "https://www.bing.com/images/search"  # серверная HTML-выдача

# движки для интерфейса: (ключ, подпись в списке)
ENGINES: list[tuple[str, str]] = [
    ("ddg", "DuckDuckGo"),
    ("bing", "Bing"),
]

SEARCH_TIMEOUT = (10, 20)      # (подключение, чтение) для страниц выдачи
DOWNLOAD_TIMEOUT = (10, 60)    # …и для самих картинок
MAX_FILE_SIZE = 100 * 1024 * 1024   # 100 МБ — та же страховка, что в программе
RESULTS_LIMIT = 100            # максимум плиток за один запрос выдачи

# ---------------------------------------------------------------- заголовки
# те же, что у загрузчика программы (app/core/downloader.py): многие CDN
# пускают только запросы «с браузерным» User-Agent

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
KNOWN_IMAGE_EXTS = set(CONTENT_EXT.values()) | {".jfif", ".tif", ".tiff"}

RETRY_STATUSES = frozenset({401, 403, 429})

# обёртка CDN Cloudflare: /cdn-cgi/image/<параметры>/<оригинал>
_CDN_WRAP_RE = re.compile(r"/cdn-cgi/image/[^/?&]+/(https?://.+)$", re.IGNORECASE)

# сессия requests, закреплённая за потоком (как в программе, v0.7.11):
# переиспользование TCP/TLS, а не новое рукопожатие на каждую картинку
_TLS = threading.local()


def _http_get():
    """requests-запрос с сессией на поток; подменённый тестами requests — без сессии."""
    if getattr(requests, "__name__", "") != "requests":
        return requests.get
    session = getattr(_TLS, "session", None)
    if session is None:
        session = requests.Session()
        _TLS.session = session
    return session.get


# ---------------------------------------------------------------- поиск


def search_web(query: str, engine: str = "ddg", offset: int = 0,
               limit: int = RESULTS_LIMIT) -> dict:
    """Найти картинки в интернете. Возвращает
    ``{"engine", "query", "results": [{"url","thumb","title","w","h","source"}]}``.

    ``offset`` — сколько результатов пропустить (для кнопки «Ещё»);
    движки переводят его по-своему (DDG — параметр ``s``, Bing — ``first``).
    Ошибки запросов — WebSearchError; пустой запрос/неизвестный движок —
    ValueError (HTTP-слой отвечает на них 400, на WebSearchError — 502).
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("пустой запрос")
    key = (engine or "ddg").lower()
    fn = _ENGINE_FN.get(key)
    if fn is None:
        raise ValueError(f"неизвестный поисковик: {engine}")
    try:
        limit = max(1, min(int(limit or RESULTS_LIMIT), RESULTS_LIMIT))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        limit, offset = RESULTS_LIMIT, 0
    try:
        results = fn(query, offset, limit)
    except (WebSearchError, ValueError):
        raise
    except Exception as exc:               # noqa: BLE001 — сетевые ошибки requests
        raise WebSearchError(f"{_engine_name(key)}: {exc}") from exc
    return {"engine": key, "query": query, "results": results}


def _engine_name(key: str) -> str:
    for k, label in ENGINES:
        if k == key:
            return label
    return key


def _search_headers() -> dict:
    return dict(BASE_HEADERS)


def _norm_result(url, thumb, title, w, h, source) -> dict | None:
    """Привести плитку выдачи к общему формату; мусор — None."""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    thumb = str(thumb or "").strip()
    if not thumb.startswith(("http://", "https://")):
        thumb = url                 # превью нет — плитка покажет оригинал
    try:
        w = int(w or 0)
        h = int(h or 0)
    except (TypeError, ValueError):
        w = h = 0
    title = html_mod.unescape(str(title or "")).strip()[:200]
    source = str(source or "").strip()
    if not source.startswith(("http://", "https://")):
        source = ""
    return {"url": url, "thumb": thumb, "title": title,
            "w": w, "h": h, "source": source}


def _dedupe(items: list[dict], limit: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for it in items:
        if it is None:
            continue
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
        if len(out) >= limit:
            break
    return out


# ---- DuckDuckGo: страница выдачи → токен vqd → JSON i.js

# vqd живёт в скриптах страницы: vqd="4-1234…", vqd='4-…', vqd=4-…&;
# формат — цифры и дефисы, поэтому шаблон устойчив к смене кавычек
_VQD_RE = re.compile(r"""vqd\s*=\s*["']?([\d][\d-]{5,})["']?""", re.IGNORECASE)


def _ddg_vqd(query: str) -> str:
    url = (f"{DDG_BASE.rstrip('/')}/?q={quote_plus(query)}"
           f"&iax=images&ia=images")
    try:
        resp = _http_get()(url, headers=_search_headers(), timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        page = resp.text
        resp.close()
    except WebSearchError:
        raise
    except Exception as exc:               # noqa: BLE001
        raise WebSearchError(f"DuckDuckGo не ответил: {exc}") from exc
    m = _VQD_RE.search(page)
    if not m:
        raise WebSearchError(
            "DuckDuckGo изменил выдачу: в странице нет токена vqd — "
            "попробуйте другой поисковик")
    return m.group(1)


def _search_ddg(query: str, offset: int, limit: int) -> list[dict]:
    vqd = _ddg_vqd(query)
    params = {"l": "wt-wt", "o": "json", "q": query, "vqd": vqd, "f": ",,,", "p": "1"}
    if offset:
        params["s"] = str(offset)          # сколько плиток пропустить (скролл выдачи)
    headers = _search_headers()
    headers["Referer"] = f"{DDG_BASE}/"
    headers["Accept"] = "application/json, text/plain, */*"
    try:
        resp = _http_get()(DDG_IJS, params=params, headers=headers,
                           timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        data = json.loads(resp.text)
        resp.close()
    except WebSearchError:
        raise
    except Exception as exc:               # noqa: BLE001
        raise WebSearchError(f"DuckDuckGo не ответил: {exc}") from exc
    rows = data.get("results") or [] if isinstance(data, dict) else []
    return _dedupe(
        [_norm_result(r.get("image"), r.get("thumbnail"), r.get("title"),
                      r.get("width"), r.get("height"), r.get("url"))
         for r in rows if isinstance(r, dict)],
        limit)


# ---- Bing: серверная HTML-выдача, у плиток атрибут m='{"murl":…}'

_BING_M_RE = re.compile(r'm="(\{[^"]+\})"')


def _search_bing(query: str, offset: int, limit: int) -> list[dict]:
    params = {"q": query, "count": "35"}
    if offset:
        params["first"] = str(offset + 1)  # «first» у Bing — с единицы
    try:
        resp = _http_get()(BING_URL, params=params, headers=_search_headers(),
                           timeout=SEARCH_TIMEOUT)
        resp.raise_for_status()
        page = resp.text
        resp.close()
    except WebSearchError:
        raise
    except Exception as exc:               # noqa: BLE001
        raise WebSearchError(f"Bing не ответил: {exc}") from exc
    items: list[dict | None] = []
    for raw in _BING_M_RE.findall(page):
        try:
            meta = json.loads(html_mod.unescape(raw))
        except Exception:                  # noqa: BLE001 — битая плитка не роняет выдачу
            continue
        if not isinstance(meta, dict):
            continue
        items.append(_norm_result(meta.get("murl"), meta.get("turl"), meta.get("t"),
                                  meta.get("w"), meta.get("h"), meta.get("purl")))
    return _dedupe(items, limit)


_ENGINE_FN = {"ddg": _search_ddg, "bing": _search_bing}


# ---------------------------------------------------------------- скачивание
# правила копируют app/core/downloader.py (программа) — см. докстринг модуля


def unwrap_cdn_url(url: str) -> str | None:
    """Раскрыть обёртку Cloudflare Image Resizing: /cdn-cgi/image/… → оригинал."""
    m = _CDN_WRAP_RE.search(url or "")
    inner = m.group(1) if m else ""
    return inner if inner.startswith(("http://", "https://")) else None


def fetch_image(url: str, referer: str = "") -> tuple[bytes, str, str]:
    """Скачать картинку, перебирая запасные варианты заголовков.

    Лестница попыток — та же, что у программы: как есть (с Referer
    страницы-источника, если он был) → без Referer → с Referer самого
    сайта картинки → раскрытая обёртка /cdn-cgi/image/. Возвращает
    ``(байты, content-type, адрес ответа)``; любая неудача —
    :class:`WebSearchError` с честной причиной. Файлы больше 100 МБ
    и ответы «не-картинка» отвергаются до записи на диск.
    """
    url = (url or "").strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https"):
        raise WebSearchError("поддерживаются только http/https-ссылки")
    origin = f"{parts.scheme}://{parts.netloc}/" if parts.netloc else ""
    attempts: list[tuple[str, str | None]] = [(url, referer or None)]
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
    last_status = 0
    http_get = _http_get()
    for attempt_url, ref in attempts:
        headers = dict(BASE_HEADERS)
        if ref:
            headers["Referer"] = ref
        try:
            resp = http_get(attempt_url, headers=headers,
                            timeout=DOWNLOAD_TIMEOUT, stream=True)
        except Exception as exc:           # noqa: BLE001 — сеть моргнула, попробуем ещё
            last_exc, last_status = exc, 0
            continue
        if resp.status_code in RETRY_STATUSES and (attempt_url, ref) != attempts[-1]:
            last_status = resp.status_code
            resp.close()
            continue
        if resp.status_code >= 400:
            last_status = resp.status_code
            resp.close()
            continue
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype and not ctype.startswith("image/"):
            resp.close()
            raise WebSearchError(f"по ссылке не картинка ({ctype})")
        try:
            data = _read_capped(resp)
        finally:
            resp.close()
        return data, ctype, resp.url or attempt_url
    if last_exc is not None:
        raise WebSearchError(f"сайт не ответил: {last_exc}")
    raise WebSearchError(f"сайт ответил ошибкой (HTTP {last_status or '?'})")


def _read_capped(resp) -> bytes:
    """Прочитать ответ целиком, не превышая MAX_FILE_SIZE (страховка памяти)."""
    try:
        declared = int(resp.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared > MAX_FILE_SIZE:
        raise WebSearchError("файл больше 100 МБ")
    buf = bytearray()
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        if chunk:
            buf.extend(chunk)
            if len(buf) > MAX_FILE_SIZE:
                raise WebSearchError("файл больше 100 МБ")
    if not buf:
        raise WebSearchError("файл пуст")
    return bytes(buf)


def sanitize_filename(name: str) -> str:
    """Оставить в имени файла только безопасные символы (как в программе)."""
    from urllib.parse import unquote
    name = unquote(name or "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:150]


def filename_from_url(url: str, content_type: str) -> str:
    """Имя файла по URL и Content-Type — те же правила, что у программы."""
    path = urlparse(url).path
    base = os.path.basename(path)
    stem, ext = os.path.splitext(sanitize_filename(base))
    if not ext or ext.lower() not in KNOWN_IMAGE_EXTS:
        ext = CONTENT_EXT.get(content_type, ext or ".jpg")
    if not stem:
        stem = f"image_{time.strftime('%Y%m%d_%H%M%S')}"
    return f"{stem}{ext}"


def create_exclusive(directory: str, filename: str) -> tuple[int, str]:
    """Атомарно-свободное имя (O_CREAT|O_EXCL): параллельные скачивания с
    одинаковым именем не затирают друг друга — проигравший берёт
    ``name-1.ext``, ``name-2.ext``… (как _create_exclusive в программе)."""
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
