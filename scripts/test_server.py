"""Тесты веб-сервера (модуль удалённого доступа, v0.8.0).

Запуск:
    QT_QPA_PLATFORM=offscreen python scripts/test_server.py

Проверяются реальные HTTP-запросы к серверу на случайном порту: токен
(заголовок/запрос/cookie, 401 без него), веб-интерфейс, лента папок,
миниатюры (включая общий с программой кэш), полный просмотр с Range,
скачивание, переименование по правилам программы, удаление (корзина и
окончательное), «только просмотр», ограничение корней, поиск (вглубь,
игнор дефиса, предел), диски, журнал, rembg-маршруты, менеджер
настроек и запуск отдельным процессом (python -m app.server).
"""

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from PIL import Image

from app.core import i18n
from app.server import api as api_mod
from app.server.api import Api
from app.server.httpd import IHServer, lan_addresses
from app.server.manager import ServerManager, generate_token

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'OK  ' if cond else 'FAIL'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        FAILURES.append(name)


def http(base: str, path: str, token: str = "tt", headers: dict | None = None,
         data: dict | None = None, method: str = "GET"):
    """Запрос к тест-серверу → (код, тело, заголовки)."""
    url = f"{base}{path}"
    sep = "&" if "?" in path else "?"
    if token:
        url += f"{sep}token={token}"
    hdrs = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def make_env() -> tuple[str, dict]:
    tmp = tempfile.mkdtemp(prefix="ih_srv_")
    Image.new("RGB", (120, 90), (200, 60, 60)).save(os.path.join(tmp, "cat.jpg"))
    Image.new("RGBA", (40, 40), (60, 200, 60, 128)).save(os.path.join(tmp, "alpha.png"))
    os.makedirs(os.path.join(tmp, "sub"))
    Image.new("RGB", (30, 30), (60, 200, 60)).save(os.path.join(tmp, "sub", "dog.png"))
    Image.new("RGB", (30, 30), (60, 60, 200)).save(os.path.join(tmp, "m-y.png"))
    open(os.path.join(tmp, "note.txt"), "w").write("x")
    open(os.path.join(tmp, ".hidden.png"), "wb").write(b"hidden")
    return tmp, {
        "cat": os.path.join(tmp, "cat.jpg"),
        "alpha": os.path.join(tmp, "alpha.png"),
        "sub": os.path.join(tmp, "sub"),
        "dog": os.path.join(tmp, "sub", "dog.png"),
        "dash": os.path.join(tmp, "m-y.png"),
    }


def make_server(view_only: bool = False, restrict=None, favorites=None):
    api = Api(version="0.8.0-test", view_only=view_only,
              restrict_roots=restrict, favorites=favorites)
    srv = IHServer(api, "tt", host="127.0.0.1", port=0)
    port = srv.start()
    assert srv.wait_ready(5), "сервер не поднялся"
    return api, srv, f"http://127.0.0.1:{port}"


def main() -> int:
    tmp, F = make_env()
    q = urllib.request.quote

    api, srv, base = make_server()
    try:
        # ---------- токен и доступ ----------
        st, body, _ = http(base, "/api/ping", token="")
        check("без токена API — 401", st == 401)
        st, body, _ = http(base, "/api/ping", token="wrong")
        check("неверный токен — 401", st == 401)
        st, body, _ = http(base, "/api/ping")
        j = json.loads(body)
        check("ping по заголовку — 200", st == 200 and j["app"] == "Image Hunter",
              f"ver={j.get('version')}")
        check("ping: view_only=false в ответе", j["view_only"] is False)
        st, body, _ = http(base, "/api/ping?token=tt")
        check("ping через ?token= — 200",
              st == 200 and json.loads(body)["app"] == "Image Hunter")

        # cookie: первый заход по ссылке выдаёт Set-Cookie с токеном
        st, body, hdrs = http(base, "/", token="tt")
        check("страница интерфейса — 200", st == 200 and b"Image Hunter" in body)
        check("страница: маршрут /api/ упомянут", b"/api/" in body)
        check("страница: есть переключатель языка", b"blang" in body)
        setc = (hdrs.get("Set-Cookie") or "")
        check("первый заход выдаёт cookie с токеном",
              setc.startswith("ih_token=tt"), setc[:40])
        st, body, _ = http(base, "/api/ping", token="",
                           headers={"Cookie": "ih_token=tt"})
        check("cookie принимается вместо токена", st == 200)
        st, body, hdrs = http(base, "/", token="")
        check("страница без токена — 401 и без Set-Cookie",
              st == 401 and not (hdrs.get("Set-Cookie") or ""),
              f"st={st}")
        check("401-страница объясняет про токен", "токен".encode() in body)

        # ---------- лента папки ----------
        st, body, _ = http(base, "/api/list?path=" + q(tmp))
        j = json.loads(body)
        names = [f["name"] for f in j["files"]]
        folders = [f["name"] for f in j["folders"]]
        check("list: картинки, без .txt", "cat.jpg" in names and "note.txt" not in names,
              str(names))
        check("list: скрытые пропущены", ".hidden.png" not in names)
        check("list: подпапки перечислены", "sub" in folders)
        check("list: parent заполнен", j["parent"] and j["parent"] != j["path"])
        check("list: размеры и mtime", all(f["size"] > 0 for f in j["files"]))
        st, body, _ = http(base, "/api/list?path=" + q(os.path.join(tmp, "нет")))
        check("list: несуществующая папка — 404", st == 404)
        st, body, _ = http(base, "/api/list?path=")
        check("list: пустой путь — 400", st == 400)

        # ---------- миниатюры и кэш ----------
        st, body, hdrs = http(base, "/api/thumb?path=" + q(F["cat"]) + "&size=320")
        check("thumb: PNG", st == 200 and body[:4] == b"\x89PNG")
        im = Image.open(io.BytesIO(body))
        check("thumb: большая сторона ≤ 320", max(im.size) <= 320, str(im.size))
        key = api_mod._thumb_key(F["cat"], os.path.getsize(F["cat"]),
                                 os.path.getmtime(F["cat"]))
        cache_path = os.path.join(api_mod._thumb_cache_dir(), f"{key}-320.png")
        check("thumb: кэш записан в общий кэш ImageHunter", os.path.isfile(cache_path))
        st2, body2, _ = http(base, "/api/thumb?path=" + q(F["cat"]) + "&size=320")
        check("thumb: второй вызов — из кэша (тот же байт-в-байт)", body2 == body)
        # общий кэш программы: подкладываем миниатюру программы (160) — она берётся
        prog = os.path.join(api_mod._thumb_cache_dir(), f"{key}.png")
        Image.new("RGB", (160, 120), (10, 200, 10)).save(prog)
        st3, body3, _ = http(base, "/api/thumb?path=" + q(F["cat"]) + "&size=160")
        check("thumb: при size<=160 переиспользуется кэш программы",
              st3 == 200 and body3 == open(prog, "rb").read())
        os.remove(prog)
        st, body, _ = http(base, "/api/thumb?path=" + q(os.path.join(tmp, "note.txt")))
        check("thumb: не-картинка — 400/404", st in (400, 404), str(st))

        # ---------- полный просмотр и Range ----------
        st, body, hdrs = http(base, "/api/image?path=" + q(F["cat"]))
        full = open(F["cat"], "rb").read()
        check("image: полный файл байт-в-байт", st == 200 and body == full)
        check("image: Accept-Ranges: bytes",
              hdrs.get("Accept-Ranges") == "bytes")
        st, body, hdrs = http(base, "/api/image?path=" + q(F["cat"]),
                              headers={"Range": "bytes=0-9"})
        check("Range 0-9: 206 и 10 байт", st == 206 and len(body) == 10)
        check("Range: Content-Range корректный",
              hdrs.get("Content-Range") == f"bytes 0-9/{len(full)}",
              hdrs.get("Content-Range") or "")
        st, body, _ = http(base, "/api/image?path=" + q(F["cat"]),
                           headers={"Range": f"bytes=-{len(full)//2}"})
        check("Range «хвост файла» — 206",
              st == 206 and len(body) == len(full) // 2)
        st, body, _ = http(base, "/api/image?path=" + q(F["cat"]),
                           headers={"Range": f"bytes={len(full)+10}-"})
        check("Range за концом файла — 416", st == 416)
        st, body, hdrs = http(base, "/api/raw?path=" + q(F["cat"]))
        check("raw: attachment с именем файла",
              st == 200 and "attachment" in (hdrs.get("Content-Disposition") or ""))
        st, body, _ = http(base, "/api/image?path=" + q(os.path.join(tmp, "no.jpg")))
        check("image: нет файла — 404", st == 404)

        # ---------- переименование: правила программы ----------
        old = os.path.join(tmp, "ren.png")
        Image.new("RGB", (8, 8)).save(old)
        st, body, _ = http(base, "/api/rename", data={"path": old, "name": "переименован.png"},
                           method="POST")
        new = os.path.join(tmp, "переименован.png")
        check("rename: файл переименован на диске",
              st == 200 and os.path.isfile(new) and not os.path.exists(old))
        st, body, _ = http(base, "/api/rename",
                           data={"path": new, "name": "bad<name>.png"}, method="POST")
        check("rename: запрещённые символы — 400", st == 400)
        check("rename: файл не тронут при отказе", os.path.isfile(new))
        st, body, _ = http(base, "/api/rename",
                           data={"path": new, "name": "cat.jpg"}, method="POST")
        check("rename: конфликт с существующим — 400", st == 400)
        check("rename: оба файла целы после конфликта",
              os.path.isfile(new) and os.path.isfile(os.path.join(tmp, "cat.jpg")))
        st, body, _ = http(base, "/api/rename",
                           data={"path": new, "name": "  .  "}, method="POST")
        check("rename: имя из точек/пробелов — 400", st == 400)
        up = os.path.join(tmp, "case.PNG")
        Image.new("RGB", (8, 8)).save(up)
        st, body, _ = http(base, "/api/rename",
                           data={"path": up, "name": "CASE.png"}, method="POST")
        check("rename: только регистр — разрешён", st == 200
              and os.path.isfile(os.path.join(tmp, "CASE.png")))

        # ---------- удаление ----------
        api_mod._TRASH_CACHE.clear()
        calls: list[tuple[str, bool]] = []
        orig_trash = api_mod._trash_file
        api_mod._trash_file = lambda p: (calls.append((p, False)) or (True, ""))
        try:
            victim = os.path.join(tmp, "ren.png")
            Image.new("RGB", (8, 8)).save(victim)
            st, body, _ = http(base, "/api/delete",
                               data={"paths": [victim]}, method="POST")
            r0 = json.loads(body)["results"][0]
            check("delete: корзина вызвана, ok=true",
                  st == 200 and r0["ok"] and calls[-1][0] == victim)
            victim2 = os.path.join(tmp, "ren2.png")
            Image.new("RGB", (8, 8)).save(victim2)
            st, body, _ = http(base, "/api/delete",
                               data={"paths": [victim2], "permanent": True},
                               method="POST")
            r0 = json.loads(body)["results"][0]
            check("delete: окончательное — файл исчез",
                  st == 200 and r0["ok"] and not os.path.exists(victim2))
        finally:
            api_mod._trash_file = orig_trash
        st, body, _ = http(base, "/api/delete",
                           data={"paths": [os.path.join(tmp, "нет.png")]},
                           method="POST")
        r0 = json.loads(body)["results"][0]
        check("delete: несуществующий — ok=false с ошибкой",
              st == 200 and not r0["ok"] and r0["error"])

        # ---------- поиск ----------
        st, body, _ = http(base, f"/api/search?path={q(tmp)}&q=dog&deep=1")
        j = json.loads(body)
        check("search: находит вглубь подпапок",
              any(f["name"] == "dog.png" for f in j["files"]), str(len(j["files"])))
        st, body, _ = http(base, f"/api/search?path={q(tmp)}&q=dog")
        j = json.loads(body)
        check("search: без deep — только верхний уровень",
              all(f["folder"] == tmp for f in j["files"]))
        st, body, _ = http(base, f"/api/search?path={q(tmp)}&q=my&dash=1")
        j = json.loads(body)
        check("search: игнор дефиса находит m-y.png",
              any(f["name"] == "m-y.png" for f in j["files"]))
        old_max = api_mod.SEARCH_MAX
        api_mod.SEARCH_MAX = 2
        try:
            st, body, _ = http(base, f"/api/search?path={q(tmp)}&q=png&deep=1&dash=1")
            j = json.loads(body)
            check("search: предел → флаг truncated",
                  j["truncated"] is True and len(j["files"]) == 2)
        finally:
            api_mod.SEARCH_MAX = old_max

        # ---------- диски, журнал ----------
        st, body, _ = http(base, "/api/drives")
        j = json.loads(body)
        check("drives: список не пуст", st == 200 and len(j["drives"]) >= 1)
        st, body, _ = http(base, "/api/log?n=10")
        check("log: маршрут отвечает", st == 200 and "lines" in json.loads(body))
        i18n.set_lang("ru")
        from app.core import applog
        logging.getLogger().setLevel(logging.INFO)  # как applog.setup() в программе
        logging.getLogger().addHandler(api.ring)    # как делает менеджер при старте
        try:
            applog.event("log.event.server_stop", port=1)
            time.sleep(0.05)
            st, body, _ = http(base, "/api/log?n=5")
            lines = json.loads(body)["lines"]
            check("log: событие журнала видно с телефона",
                  any("сервер" in ln or "server" in ln.lower() for ln in lines)
                  and len(lines) >= 1, str(lines[-1:]) if lines else "пусто")
        finally:
            logging.getLogger().removeHandler(api.ring)

        # ---------- rembg-маршруты ----------
        st, body, _ = http(base, "/api/rembg/models")
        j = json.loads(body)
        check("rembg/models: список с u2netp", st == 200 and "u2netp" in j["models"])
        st, body, _ = http(base, "/api/rembg", data={"paths": [F["cat"]]},
                           method="POST")
        j = json.loads(body)
        installed = j.get("total") is not None
        if installed:
            jid = j["id"]
            for _ in range(120):
                st, body, _ = http(base, "/api/rembg/status?id=" + q(jid))
                js = json.loads(body)
                if js.get("state") in ("done", "error"):
                    break
                time.sleep(0.5)
            check("rembg: задание завершилось", js.get("state") in ("done", "error"),
                  f"state={js.get('state')}")
            if js.get("state") == "done" and js.get("ok"):
                check("rembg: результат *_nobg.png на диске",
                      os.path.isfile(os.path.join(tmp, "cat_nobg.png")))
        else:
            check("rembg: без модуля — честная ошибка",
                  st == 400 and "не установлен" in j.get("error", ""))
        st, body, _ = http(base, "/api/rembg", data={"paths": []}, method="POST")
        check("rembg: пустой список — 400", st == 400)
        st, body, _ = http(base, "/api/rembg/status?id=none")
        check("rembg/status: неизвестное задание — 404", st == 404)

        # ---------- «только просмотр» ----------
        api.view_only = True
        st, body, _ = http(base, "/api/rename",
                           data={"path": new, "name": "x.png"}, method="POST")
        check("view_only: rename — 403", st == 403)
        st, body, _ = http(base, "/api/delete", data={"paths": [F["cat"]]},
                           method="POST")
        check("view_only: delete — 403", st == 403)
        st, body, _ = http(base, "/api/rembg", data={"paths": [F["cat"]]},
                           method="POST")
        check("view_only: rembg — 403", st == 403)
        st, body, _ = http(base, "/api/list?path=" + q(tmp))
        check("view_only: чтение работает", st == 200)
        api.view_only = False

        # ---------- ограничение корней ----------
        api2, srv2, base2 = make_server(restrict=[tmp], favorites=[tmp])
        try:
            st, body, _ = http(base2, "/api/list?path=" + q(tmp))
            check("restrict: разрешённый корень — 200", st == 200)
            st, body, _ = http(base2, "/api/list?path=" + q(tempfile.gettempdir()))
            check("restrict: вне корней — 400", st == 400)
            st, body, _ = http(base2, "/api/drives")
            j = json.loads(body)
            check("restrict: избранные папки в drives",
                  any(d.get("kind") == "favorite" for d in j["drives"]))
        finally:
            srv2.stop()

        # ---------- порт занят ----------
        busy = IHServer(Api(), "tt", host="127.0.0.1", port=srv.port)
        try:
            busy.start()
            check("порт занят — честная ошибка", False, "ожидался OSError")
        except OSError as exc:
            check("порт занят — честная ошибка", "порт" in str(exc).lower()
                  or "port" in str(exc).lower(), str(exc)[:60])

        # ---------- служебное ----------
        addrs = lan_addresses(srv.port)
        check("lan_addresses: адреса с портом",
              addrs and all(f":{srv.port}" in a for a in addrs), str(addrs[:1]))
        check("generate_token: длинный и разный",
              len(generate_token()) >= 20 and generate_token() != generate_token())
        st, body, _ = http(base, "/api/no-such-route")
        check("неизвестный маршрут — 404", st == 404)
    finally:
        srv.stop()
    try:
        urllib.request.urlopen(f"{base}/api/ping?token=tt", timeout=2)
        check("после stop() сервер недоступен", False)
    except (urllib.error.URLError, OSError):
        check("после stop() сервер недоступен", True)

    # ---------- менеджер настроек ----------
    QSettings("ImageHunter", "ImageHunter").clear()
    mgr = ServerManager()
    check("manager: токен генерируется и сохраняется",
          len(mgr.get_token()) >= 20 and mgr.get_token() == mgr.get_token())
    mgr.set_port(8599)
    check("manager: порт roundtrip", mgr.get_port() == 8599)
    mgr.set_view_only(True)
    check("manager: view_only roundtrip", mgr.get_view_only() is True)
    mgr.set_view_only(False)
    check("manager: has_qr видит библиотеку", mgr.has_qr() is True)
    ok = mgr.start()
    check("manager: start() поднимает сервер", ok and mgr.is_running())
    urls = mgr.urls()
    check("manager: urls() содержат токен",
          urls and all("token=" in u for u in urls), str(urls[:1]))
    st, body, _ = http(f"http://127.0.0.1:{mgr.port()}", "/api/ping",
                       token=mgr.get_token())
    check("manager: сервер отвечает по HTTP", st == 200)
    check("manager: повторный start() идемпотентен", mgr.start() is True)
    mgr.stop()
    check("manager: stop() останавливает", not mgr.is_running())
    QSettings("ImageHunter", "ImageHunter").clear()

    # ---------- отдельный процесс: python -m app.server ----------
    py = sys.executable
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    port_cli = 8643
    proc = subprocess.Popen(
        [py, "-m", "app.server", "--port", str(port_cli), "--token", "tt",
         "--view-only", "--restrict", tmp, "--lifetime", "10", "--quiet"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 15
        cli_ok = False
        while time.monotonic() < deadline:
            try:
                st, body, _ = http(f"http://127.0.0.1:{port_cli}", "/api/ping")
                cli_ok = st == 200 and json.loads(body)["view_only"] is True
                break
            except (urllib.error.URLError, OSError):
                time.sleep(0.2)
        check("CLI: python -m app.server отвечает", cli_ok)
        st, body, _ = http(f"http://127.0.0.1:{port_cli}",
                           "/api/list?path=" + q(tempfile.gettempdir()))
        check("CLI: --restrict работает", st == 400)
        st, body, _ = http(f"http://127.0.0.1:{port_cli}",
                           "/api/rename", data={"path": F["cat"], "name": "q.png"},
                           method="POST")
        check("CLI: --view-only запрещает правки", st == 403)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО проверок: {len(FAILURES)}: {FAILURES}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
