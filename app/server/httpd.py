"""Маленький HTTP-сервер Image Hunter — stdlib, без зависимостей.

ThreadingHTTPServer (поток на запрос, daemon-потоки) + один обработчик,
который раздаёт:

* ``GET /``              — мобильный веб-интерфейс (webui.PAGE);
* ``GET /api/ping``      — информация о программе;
* ``GET /api/drives``    — диски и избранные папки;
* ``GET /api/list``      — содержимое папки (``?path=``);
* ``GET /api/search``    — поиск по имени (``?path=&q=&deep=&dash=``);
* ``GET /api/thumb``     — миниатюра PNG (``?path=&size=``);
* ``GET /api/image``     — полная картинка, с докачкой Range;
* ``GET /api/raw``       — файл «скачать на устройство» (attachment);
* ``GET /api/web/search`` — поиск картинок в интернете (``?engine=&q=&offset=``);
* ``GET /api/web/proxy`` — картинка по внешней ссылке (``?url=``, ``&dl=1`` —
  attachment: телефон смотрит оригинал и сохраняет его через сервер, —
  сайты с проверкой Referer чужие страницы не пускают);
* ``POST /api/web/download`` — скачать картинки по ссылкам в папку
  (тело: urls, folder) — фоновое задание;
* ``GET /api/job/status?id=`` — статус фонового задания (rembg и webdl);
* ``GET /api/log``       — хвост журнала (``?n=``);
* ``GET /api/rembg/models`` — доступные модели;
* ``POST /api/rembg``    — запустить удаление фона (тело: paths, model);
* ``GET /api/rembg/status?id=`` — статус задания (алиас /api/job/status);
* ``POST /api/rename``   — переименовать (тело: path, name);
* ``POST /api/delete``   — удалить (тело: paths, permanent).

Безопасность: у каждого запроса проверяется токен — из ``?token=``,
заголовка ``X-IH-Token`` или cookie ``ih_token`` (её выдаёт первый
заход по ссылке с токеном). Сравнение постоянным временем
(hmac.compare_digest). Неавторизованному отдаётся 401 — и страница «/»,
и API. В запросе не логируются путь и токен: журнал не должен стать
источником утечки.

Ошибки API — JSON ``{"error": "…"}`` с честным кодом: 400 (плохой
запрос), 403 (только просмотр / вне корней), 404 (не найдено),
502 (поисковик или сайт с картинкой не ответил), 500.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.core import applog
from app.server import api as api_mod
from app.server import websearch
from app.server import webui

_MAX_JSON = 1 << 20          # тело POST не больше 1 МБ
_RANGE_CHUNK = 1 << 20       # читаем Range кусками не больше 1 МБ в память


class IHServer:
    """Жизнь HTTP-сервера: start()/stop() из любого потока."""

    def __init__(self, api: api_mod.Api, token: str, host: str = "0.0.0.0",
                 port: int = 8477):
        self.api = api
        self.token = token
        self.host = host
        self.port = port
        self._srv: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._ready.is_set() and self._thread is not None \
            and self._thread.is_alive()

    def start(self) -> int:
        """Поднять сервер; возвращает фактический порт (полезно при port=0)."""
        if self.running:
            return self.port
        srv = _make_server(self.api, self.token, self.host, self.port)
        self._srv = srv
        self.port = srv.server_address[1]
        self._thread = threading.Thread(
            target=self._serve, args=(srv,), daemon=True,
            name=f"ih-web-{self.port}")
        self._thread.start()
        self._ready.set()
        return self.port

    def _serve(self, srv: ThreadingHTTPServer) -> None:
        try:
            srv.serve_forever(poll_interval=0.25)
        except Exception as exc:               # noqa: BLE001
            logging.getLogger("app").error("web server: %s", exc)

    def stop(self) -> None:
        self._ready.clear()
        srv = self._srv
        self._srv = None
        if srv is None:
            return
        try:
            srv.shutdown()                     # останавливает serve_forever
        except Exception:                      # noqa: BLE001
            pass
        try:
            srv.server_close()
        except Exception:                      # noqa: BLE001
            pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """Дождаться, пока порт начнёт принимать соединения (для тестов/CLI)."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.3):
                    return True
            except OSError:
                time.sleep(0.05)
        return False


class _Handler(BaseHTTPRequestHandler):
    """Все маршруты; api/token живут в атрибутах класса (см. _make_server)."""
    server_version = "ImageHunter/0.8"
    protocol_version = "HTTP/1.1"          # keep-alive: телефон не рвёт соединения

    # ---- служебное -----------------------------------------------------

    def log_message(self, fmt, *args):     # noqa: N802 (BaseHTTPRequestHandler API)
        pass                               # access-лог не нужен: шумит и пишет пути

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict[str, str] | None = None) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            extra = extra or {}
            self.send_header("Cache-Control", extra.pop("Cache-Control", "no-store"))
            for k, v in extra.items():
                self.send_header(k, v)
            if self._extra_cookie:
                self.send_header("Set-Cookie", self._extra_cookie)
                self._extra_cookie = None
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                            # телефон ушёл — не беда

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, text: str) -> None:
        self._json({"error": text}, code)

    def _token_ok(self) -> bool:
        token = getattr(self.server, "ih_token", "")
        if not token:
            return False
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        given = (q.get("token", [""])[0]
                 or self.headers.get("X-IH-Token", "")
                 or _cookie_token(self.headers.get("Cookie", "")))
        return bool(given) and hmac.compare_digest(given, token)

    def _authed_or_401(self) -> bool:
        if self._token_ok():
            return True
        self._json({"error": "нужен токен доступа"}, 401)
        return False

    _extra_cookie: str | None = None

    def _set_token_cookie(self) -> None:
        """Первый заход по ссылке с ?token= запомнить cookie — дальше адрес
        можно набирать без токена. Вызывается ТОЛЬКО на авторизованном
        запросе: cookie с токеном нельзя выдавать тому, кто токена не дал."""
        token = getattr(self.server, "ih_token", "")
        if not token:
            return
        self._extra_cookie = (f"ih_token={token}; Path=/; Max-Age=31536000; "
                              "SameSite=Strict; HttpOnly")

    def _api(self) -> None:
        """Маршруты GET /api/..."""
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        api: api_mod.Api = self.server.ih_api
        route = u.path.rstrip("/") or "/api"
        try:
            if route == "/api/ping":
                self._json(api.ping())
            elif route == "/api/drives":
                self._json({"drives": api.drives()})
            elif route == "/api/list":
                self._json(api.list_folder(q.get("path", "")))
            elif route == "/api/search":
                self._json(api.search(
                    q.get("path", ""), q.get("q", ""),
                    deep=q.get("deep") in ("1", "true", "yes"),
                    ignore_dash=q.get("dash") in ("1", "true", "yes")))
            elif route == "/api/thumb":
                data, mtime = api.thumbnail(q.get("path", ""),
                                            _int(q.get("size"),
                                                 api_mod.THUMB_SIZE_DEFAULT))
                self._send(200, data, "image/png", {"Cache-Control":
                            "private, max-age=86400"})
            elif route == "/api/image":
                self._send_image(q.get("path", ""))
            elif route == "/api/raw":
                self._send_image(q.get("path", ""), attachment=True)
            elif route == "/api/log":
                self._json(api.log_tail(_int(q.get("n"), 100)))
            elif route == "/api/job/status":
                self._json(api.job_status(q.get("id", "")))
            elif route == "/api/rembg/status":
                self._json(api.job_status(q.get("id", "")))
            elif route == "/api/rembg/models":
                self._json({"models": api.rembg_models(),
                            "installed": api.rembg_installed()})
            elif route == "/api/web/search":
                self._json(api.web_search(q.get("engine", "ddg"),
                                          q.get("q", ""),
                                          _int(q.get("offset"), 0)))
            elif route == "/api/web/proxy":
                self._send_web_proxy(q)
            else:
                self._err(404, f"нет такого маршрута: {route}")
        except PermissionError as exc:
            self._err(403, str(exc))
        except KeyError:
            self._err(404, "задание не найдено")
        except FileNotFoundError as exc:
            self._err(404, f"не найдено: {exc}")
        except ValueError as exc:
            self._err(400, str(exc))
        except websearch.WebSearchError as exc:
            self._err(502, str(exc))
        except Exception as exc:               # noqa: BLE001
            applog.error(f"web api {route}: {exc}")
            self._err(500, str(exc))

    def _send_web_proxy(self, q: dict) -> None:
        """Картинка по внешней ссылке: телефон смотрит оригинал через сервер
        (сайты с проверкой Referer чужие страницы не пускают) и сохраняет
        его на устройство (``&dl=1`` — attachment)."""
        api: api_mod.Api = self.server.ih_api
        data, ctype, fname = api.web_proxy(q.get("url", ""))
        extra = {"Cache-Control": "private, max-age=3600"}
        if q.get("dl") in ("1", "true", "yes"):
            extra["Content-Disposition"] = f'attachment; filename="{fname}"'
        self._send(200, data, ctype, extra)

    def _send_image(self, path: str, attachment: bool = False) -> None:
        api: api_mod.Api = self.server.ih_api
        path = api._check_path(path)
        try:
            total = _safe_size(path)
        except OSError as exc:
            raise FileNotFoundError(path) from exc
        data_ctype = api_mod.content_type_for(path)
        fname = urllib.parse.quote(os.path.basename(path))
        base_headers = {"Accept-Ranges": "bytes",
                        "Cache-Control": "private, max-age=3600"}
        if attachment:
            base_headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{fname}"
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start, end = _parse_range(rng, total)
            if start is None:
                self._send(416, b"", "text/plain",
                           {"Content-Range": f"bytes */{total}"})
                return
            # конец резаем по бюджету чтения: Content-Range обязан совпадать
            # с тем, что реально уйдёт в теле ответа
            end = min(end, total - 1, start + _RANGE_CHUNK * 16 - 1)
            length = end - start + 1
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    body = f.read(length)
            except OSError as exc:
                raise FileNotFoundError(str(exc)) from exc
            headers = dict(base_headers)
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
            self._send(206, body, data_ctype, headers)
            return
        data, _ct, _mtime = api.image_bytes(path)
        self._send(200, data, data_ctype, base_headers)

    # ---- методы --------------------------------------------------------

    def do_GET(self) -> None:                  # noqa: N802 (BaseHTTPRequestHandler API)
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/" or not u.path.startswith("/api"):
            if not self._token_ok():
                self._send(401, webui.PAGE_401.encode("utf-8"),
                           "text/html; charset=utf-8")
                return
            self._set_token_cookie()          # cookie — только проверенному
            if u.path in ("/", "/index.html"):
                self._send(200, webui.PAGE.encode("utf-8"),
                           "text/html; charset=utf-8")
                return
            self._err(404, "нет такой страницы")
            return
        if not self._authed_or_401():
            return
        self._api()

    def do_HEAD(self) -> None:                 # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:                 # noqa: N802
        if not self._authed_or_401():
            return
        u = urllib.parse.urlsplit(self.path)
        route = u.path.rstrip("/")
        api: api_mod.Api = self.server.ih_api
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > _MAX_JSON:
            self._err(413, "слишком большое тело запроса")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")
                                 or "{}")
        except (ValueError, UnicodeDecodeError):
            self._err(400, "тело запроса — не JSON")
            return
        try:
            if route == "/api/rename":
                self._json(api.rename(payload.get("path", ""),
                                      payload.get("name", "")))
            elif route == "/api/delete":
                self._json(api.delete(payload.get("paths", []),
                                      permanent=bool(payload.get("permanent"))))
            elif route == "/api/web/download":
                res = api.web_download_start(payload.get("urls", []),
                                             payload.get("folder", ""))
                self._json(res, 202)
            elif route == "/api/rembg":
                res = api.rembg_start(payload.get("paths", []),
                                      model=payload.get("model", ""))
                self._json(res, 202)
            else:
                self._err(404, f"нет такого маршрута: {route}")
        except PermissionError as exc:
            self._err(403, str(exc))
        except FileExistsError as exc:
            self._err(400, str(exc))
        except FileNotFoundError as exc:
            self._err(404, f"не найдено: {exc}")
        except (ValueError, KeyError, RuntimeError) as exc:
            # RuntimeError — отказ по существу (модуль не установлен и т.п.)
            self._err(400, str(exc))
        except websearch.WebSearchError as exc:
            self._err(502, str(exc))
        except Exception as exc:               # noqa: BLE001
            applog.error(f"web api {route}: {exc}")
            self._err(500, str(exc))


def _cookie_token(header: str) -> str:
    for part in header.split(";"):
        k, _eq, v = part.strip().partition("=")
        if k == "ih_token":
            return v
    return ""


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_size(path: str) -> int:
    st = os.stat(path)
    return st.st_size


def _parse_range(header: str, total: int) -> tuple[int | None, int]:
    """bytes=START-END (END может отсутствовать). start=None — диапазон плох."""
    try:
        spec = header.split("=", 1)[1]
        first = spec.split(",")[0].strip()
        start_s, _, end_s = first.partition("-")
        if not start_s:                        # bytes=-500 — хвост файла
            tail = int(end_s)
            return max(0, total - tail), total - 1
        start = int(start_s)
        end = int(end_s) if end_s else min(start + _RANGE_CHUNK * 16, total - 1)
        if start >= total:
            return None, 0
        return start, end
    except (ValueError, IndexError):
        return None, 0


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, api, token):
        super().__init__(addr, handler)
        self.ih_api = api
        self.ih_token = token


def _make_server(api: api_mod.Api, token: str, host: str, port: int) -> _Server:
    try:
        return _Server((host, port), _Handler, api, token)
    except OSError as exc:
        raise OSError(
            f"не удалось занять порт {port}: {exc}. "
            "Возможно, сервер уже запущен (или порт занят другой программой)."
        ) from exc


def lan_addresses(port: int) -> list[str]:
    """IP-адреса машины в локальных сетях (без пакетов в интернет).

    Основной путь — UDP-подключение к произвольному адресу (пакет не
    отправляется, но ОС подскажет исходный интерфейс); запасной — gethostbyname_ex.
    """
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0)
            s.connect(("8.8.8.8", 80))         # не отправляет ничего
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    if not ips:
        ips = ["127.0.0.1"]
    return [f"http://{ip}:{port}" for ip in ips]
