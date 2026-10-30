"""Тест запасных попыток загрузчика при 401/403/429 (fetch_image) и CDN-обёрток.

Проверяется:
1. unwrap_cdn_url раскрывает обёртку Cloudflare /cdn-cgi/image/<params>/<оригинал>;
2. 403 при наличии Referer → повтор без Referer;
3. 403 без Referer → повтор с Referer самого сайта картинки;
4. обёртка /cdn-cgi/image/: все попытки по обёртке 403 → запрос раскрытого
   оригинала, имя файла в _DownloadTask — по фактическому URL ответа;
5. 404 не перебирается (одна попытка, сразу ошибка);
6. сетевое исключение на первой попытке → вторая попытка спасает;
7. исчерпание всех попыток → последняя ошибка (403) уходит в статус строки;
8. обычный 200 отрабатывает одной попыткой с Referer как был;
9. дубликаты попыток не делаются (Referer уже равен origin и т.п.).

Запуск:
    QT_QPA_PLATFORM=offscreen python scripts/test_download_fallback.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


from app.core import downloader  # noqa: E402
from app.core.downloader import Downloader, _DownloadTask, fetch_image, unwrap_cdn_url  # noqa: E402

ZID_URL = ("https://media.zid.store/cdn-cgi/image/w=1200,h=630,q=90,fit=pad,"
           "background=white/https://media.zid.store/fdb0f513-2071-47da-9a77"
           "-5ebb31519af0/42c8603a-271e-465c-a1c3-fecceba73f4b.png")
ZID_INNER = ("https://media.zid.store/fdb0f513-2071-47da-9a77-5ebb31519af0/"
             "42c8603a-271e-465c-a1c3-fecceba73f4b.png")


class FakeResp:
    def __init__(self, status=200, url="", headers=None):
        self.status_code = status
        self.url = url
        self.headers = headers or {"Content-Type": "image/png"}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise downloader.requests.exceptions.HTTPError(
                f"{self.status_code} Client Error for url: {self.url}")

    def iter_content(self, chunk_size=65536):
        yield b"\x89PNG-fake-image-bytes"

    def close(self):
        self.closed = True


class FakeRequests:
    """Подмена requests.get: решение по правилам test-функции."""

    def __init__(self, rule):
        self.rule = rule          # rule(url, headers) -> FakeResp | Exception
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None, stream=True):
        self.calls.append((url, dict(headers or {})))
        res = self.rule(url, dict(headers or {}))
        if isinstance(res, Exception):
            raise res
        return res

    class exceptions:  # noqa: N270 — имитация requests.exceptions
        class HTTPError(Exception):
            pass


def patch_requests(rule) -> FakeRequests:
    fake = FakeRequests(rule)
    downloader.requests = fake  # type: ignore[assignment]
    return fake


def main() -> int:
    # ---- 1. unwrap_cdn_url -------------------------------------------------
    check("unwrap_cdn_url: обёртка zid.store раскрыта",
          unwrap_cdn_url(ZID_URL) == ZID_INNER, unwrap_cdn_url(ZID_URL) or "None")
    check("unwrap_cdn_url: обычный URL -> None",
          unwrap_cdn_url("https://example.com/pic.jpg") is None)
    check("unwrap_cdn_url: пустой -> None", unwrap_cdn_url("") is None)

    serp = "https://duckduckgo.com/?q=x&iax=images&ia=images"

    # ---- 2. 403 с Referer -> повтор без Referer ----------------------------
    fake = patch_requests(lambda u, h: FakeResp(
        status=403 if h.get("Referer") else 200, url=u))
    resp = fetch_image("https://cdn.shop.example/pic.jpg", serp)
    check("403 с Referer: спасает повтор без Referer", resp.status_code == 200)
    check("403 с Referer: две попытки", len(fake.calls) == 2,
          f"попыток: {len(fake.calls)}")
    check("первая попытка — с Referer выдачи",
          fake.calls[0][1].get("Referer") == serp)
    check("вторая попытка — без Referer", "Referer" not in fake.calls[1][1])

    # ---- 3. 403 всегда без Referer -> повтор с origin-Referer --------------
    fake = patch_requests(lambda u, h: FakeResp(
        status=403 if "Referer" not in h else 200, url=u))
    resp = fetch_image("https://cdn.shop.example/pic.jpg", None)
    check("403 без Referer: спасает Referer самого сайта",
          resp.status_code == 200 and "Referer" in fake.calls[-1][1])
    check("Referer == origin картинки",
          fake.calls[-1][1].get("Referer") == "https://cdn.shop.example/")

    # ---- 4. обёртка CDN: оригинал раскрыт, имя — по фактическому URL -------
    fake = patch_requests(lambda u, h: FakeResp(
        status=403 if u != ZID_INNER else 200, url=u,
        headers={"Content-Type": "image/png"}))

    tmpdir = tempfile.mkdtemp()
    got: dict = {}
    dl = Downloader()
    dl.status_changed.connect(lambda rid, st, info: got.update(st=st, info=info))
    row_id, _url = dl.add([ZID_URL])[0]
    # задачу вызываем синхронно: emit из того же потока доставляется напрямую
    _DownloadTask(dl, row_id, ZID_URL, serp, tmpdir).run()
    check("обёртка CDN: файл скачан через раскрытый оригинал",
          got.get("st") == "ok", str(got))
    saved = os.listdir(tmpdir)
    check("имя файла взято из раскрытого оригинала (.png)",
          bool(saved) and saved[0].endswith(".png"), str(saved))
    inner_calls = [c for c in fake.calls if c[0] == ZID_INNER]
    check("запрос раскрытого оригинала был", bool(inner_calls))
    check("файл не пуст", bool(saved) and
          os.path.getsize(os.path.join(tmpdir, saved[0])) > 0)

    # ---- 5. 404 не перебирается -------------------------------------------
    fake = patch_requests(lambda u, h: FakeResp(status=404, url=u))
    try:
        fetch_image("https://cdn.shop.example/gone.jpg", serp)
        check("404: исключение поднято", False)
    except Exception as exc:
        check("404: исключение поднято", "404" in str(exc), str(exc)[:60])
    check("404: ровно одна попытка", len(fake.calls) == 1, f"{len(fake.calls)}")

    # ---- 6. сетевое исключение -> вторая попытка ---------------------------
    fake = patch_requests(lambda u, h: (
        ConnectionError("reset by peer") if len(fake.calls) == 1
        else FakeResp(status=200, url=u)))
    resp = fetch_image("https://cdn.shop.example/pic.jpg", serp)
    check("сетевое исключение: вторая попытка спасает", resp.status_code == 200)
    check("сетевое исключение: две попытки", len(fake.calls) == 2,
          f"{len(fake.calls)}")

    # ---- 7. все попытки 403 -> последняя ошибка в статусе строки -----------
    fake = patch_requests(lambda u, h: FakeResp(status=403, url=u))
    try:
        fetch_image("https://cdn.shop.example/pic.jpg", serp)
        check("все 403: исключение поднято", False)
    except Exception as exc:
        check("все 403: исключение поднято", "403" in str(exc), str(exc)[:60])
    check("все 403: перебраны все попытки (Referer, без, origin)",
          len(fake.calls) == 3, f"{len(fake.calls)}")

    # ---- 8. обычный 200: одна попытка, Referer как был ---------------------
    fake = patch_requests(lambda u, h: FakeResp(status=200, url=u))
    fetch_image("https://cdn.shop.example/pic.jpg", serp)
    check("200: одна попытка, без запасных", len(fake.calls) == 1,
          f"{len(fake.calls)}")
    check("200: Referer выдачи сохранён",
          fake.calls[0][1].get("Referer") == serp)

    # ---- 9. без дубликатов: Referer уже равен origin -----------------------
    fake = patch_requests(lambda u, h: FakeResp(status=200, url=u))
    fetch_image("https://cdn.shop.example/pic.jpg", "https://cdn.shop.example/")
    check("Referer == origin: дубль-попытка не делается", len(fake.calls) == 1,
          f"{len(fake.calls)}")

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} → {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)
