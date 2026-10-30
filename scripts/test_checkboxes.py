"""Offscreen-тест чекбоксов Image Hunter на мок-странице выдачи.

Проверяется:
1. на каждой плитке появился ровно один чекбокс (не-картинки — без чекбоксов);
2. «лучший» кандидат для каждой плитки — настоящий оригинал
   (origUrl из data-bem, img_url, u= прокси DDG, murl Bing);
3. клики по чекбоксам обновляют счётчик и список отмеченных;
4. MutationObserver подхватывает плитки, догруженные после первого прохода;
5. повторный клик снимает отметку.

Запуск:
    QT_QPA_PLATFORM=offscreen python scripts/test_checkboxes.py [--live]

--live: дополнительная проверка на настоящей выдаче Яндекса (нужен интернет).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def run_js(page, code: str, timeout_ms: int = 15000):
    """Выполнить JS и дождаться результата (собственный цикл событий)."""
    from PySide6.QtCore import QEventLoop, QTimer

    box: dict = {}
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)

    def done(res):
        if timer.isActive():
            box["v"] = res
            timer.stop()
            loop.quit()

    def on_timeout():
        loop.quit()

    timer.timeout.connect(on_timeout)
    timer.start(timeout_ms)

    page.runJavaScript(code, done)
    loop.exec()
    return box.get("v")


def wait_ms(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def load_page(view, url, wait_ms_after: int = 0) -> bool:
    from PySide6.QtCore import QEventLoop, QUrl

    loop = QEventLoop()
    state = {"ok": False}

    def on_load(ok: bool):
        state["ok"] = ok
        loop.quit()

    view.loadFinished.connect(on_load)
    view.load(QUrl(url))
    loop.exec()
    view.loadFinished.disconnect(on_load)
    if wait_ms_after:
        wait_ms(wait_ms_after)
    return state["ok"]


CLICK_ALL_JS = """
[...document.querySelectorAll('.ih-cb')].forEach((cb) => { cb.click(); })
"""

CLICK_UNCHECKED_JS = """
[...document.querySelectorAll('.ih-cb')].forEach((cb) => {
  if (!cb.querySelector('input').checked) cb.click();
})
"""


def run_mock_test() -> None:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_serp.html")
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    check("мок-страница загрузилась", load_page(view, f"file://{mock}"))

    # мусорный data-bem на body (как в реальном Яндексе) — не должен дать чекбокс на body
    run_js(view.page(),
           "document.body.setAttribute('data-bem','{\\\"i-global\\\":{\\\"login\\\":\\\"x\\\"}}')")

    inject_checkbox_ui(view.page())
    wait_ms(900)

    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("чекбоксы на всех 5 плитках", n_boxes == 5, f"найдено: {n_boxes}")

    body_cb = run_js(view.page(), "document.querySelectorAll('body > .ih-cb').length")
    check("на body нет чекбокса", body_cb == 0, f"{body_cb}")

    plain = run_js(view.page(), """
        (() => {
          const a = [...document.querySelectorAll('a')]
            .find((x) => x.href.startsWith('https://example.com/some/page'));
          return a ? !!a.querySelector('.ih-cb') : null;
        })()
    """)
    check("обычная ссылка без чекбокса", plain is False, f"{plain}")

    # кликаем по всем чекбоксам
    run_js(view.page(), CLICK_ALL_JS)
    wait_ms(200)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("счётчик отмеченных == 5", count == 5, f"{count}")

    got: dict = {}
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    items = got.get("items", [])
    check("fetch_checked_selections вернул 5", len(items) == 5, f"{len(items)}")

    bests = {it["best"] for it in items}
    expected = {
        "https://avatars.mds.yandex.net/get-mpic/111/2a0000abc/orig",  # origUrl > img_url
        "https://example.org/pic2.jpg",                                # img_url
        "https://realsite.com/pic3.jpg",                               # u= прокси DDG
        "https://bingorig.com/pic4.jpg",                               # murl Bing
        "https://avatars.mds.yandex.net/get-mpic/999/state_orig/orig",  # data-state -> origUrl
    }
    check("набор лучших ссылок верный", bests == expected,
          f"лишние: {bests - expected}; не хватает: {expected - bests}")

    it1 = next((it for it in items
                if it["best"] == "https://avatars.mds.yandex.net/get-mpic/111/2a0000abc/orig"),
               None)
    check("оригинал из data-bem выбран первым", it1 is not None,
          f"alts: {it1['alts'][:2] if it1 else '-'}")

    # снятие отметки
    run_js(view.page(),
           "document.querySelectorAll('.ih-cb')[0].click()")
    wait_ms(200)
    count2 = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("снятие отметки уменьшает счётчик", count2 == 4, f"{count2}")

    # динамическая плитка (как при бесконечной прокрутке): observer должен подхватить
    run_js(view.page(), """
        (() => {
          const d = document.createElement('div');
          d.className = 'serp-item';
          d.innerHTML = '<a href="https://ya.ru/images/search?pos=4&amp;img_url=' +
            'https%3A%2F%2Fexample.org%2Fpic5.jpg&amp;rpt=simage">' +
            '<img src="https://avatars.mds.yandex.net/get-mpic/555/thumb5.jpg" alt="5"></a>';
          document.body.insertBefore(d, document.querySelector('p'));
        })()
    """)
    wait_ms(1600)  # debounce observer'а 400 мс + запас
    n_after = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("MutationObserver догрузил 6-ю плитку", n_after == 6, f"{n_after}")

    run_js(view.page(), CLICK_UNCHECKED_JS)
    wait_ms(200)
    count3 = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("все 6 плиток отмечены (5 старых + новая)", count3 == 6, f"{count3}")

    got2: dict = {}
    loop2 = QEventLoop()

    def on_sel2(items):
        got2["items"] = items
        loop2.quit()

    from app.core.extractor import fetch_checked_selections as _f2
    _f2(view.page(), on_sel2)
    loop2.exec()
    items2 = got2.get("items", [])
    bests2 = {it["best"] for it in items2}
    check("оригинал динамической плитки в списке",
          "https://example.org/pic5.jpg" in bests2, f"{sorted(bests2)}")

    view.deleteLater()


def run_live_test() -> None:
    """Живая выдача Яндекса: чекбоксы появились, оригиналы доступны."""
    import requests

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui
    from app.ui.web_search import is_image_search_url

    check("is_image_search_url(ya.ru/images/search)", is_image_search_url(
        "https://ya.ru/images/search?text=cats"))
    check("is_image_search_url(другой сайт) == False", not is_image_search_url(
        "https://example.com/"))

    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    ok = load_page(view, "https://ya.ru/images/search?text=28113-2P100",
                   wait_ms_after=5000)
    check("ya.ru загрузился", ok)

    inject_checkbox_ui(view.page())
    wait_ms(2500)
    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    if not n_boxes:
        print("[SKIP] живая выдача: плиток нет (возможно, капча) — пропускаем")
        return
    check("чекбоксы на живой выдаче", bool(n_boxes), f"плиток: {n_boxes}")

    # отмечаем первые 3 плитки
    run_js(view.page(), """
        [...document.querySelectorAll('.ih-cb')].slice(0, 3).forEach((cb) => cb.click());
    """)
    wait_ms(300)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("отметились первые 3 плитки", count == 3, f"{count}")

    got: dict = {}
    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    items = got.get("items", [])
    print(f"      оригиналы с живой выдачи ({len(items)}):")
    for it in items[:3]:
        print(f"        best: {it['best'][:110]}")
    ok_urls = 0
    for it in items[:3]:
        try:
            r = requests.head(it["best"], timeout=15, allow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"})
            ctype = r.headers.get("Content-Type", "")
            if r.status_code == 200 and ctype.startswith("image/"):
                ok_urls += 1
            else:
                print(f"      [warn] {r.status_code} {ctype} {it['best'][:90]}")
        except Exception as exc:  # noqa: BLE001
            print(f"      [warn] {exc} {it['best'][:90]}")
    check("живые оригиналы доступны по HTTP", ok_urls == min(len(items), 3) and ok_urls > 0,
          f"{ok_urls}/{min(len(items), 3)}")

    view.deleteLater()


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

    if "--live" in sys.argv:
        run_live_test()
    else:
        run_mock_test()

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} → {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
