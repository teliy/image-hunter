"""Offscreen-тест чекбоксов Image Hunter на мок-странице выдачи.

Проверяется:
1. на каждой плитке появился ровно один чекбокс (не-картинки — без чекбоксов);
2. «лучший» кандидат для каждой плитки — настоящий оригинал
   (origUrl из data-bem, img_url, u= прокси DDG, murl Bing);
3. клики по чекбоксам обновляют счётчик и список отмеченных;
4. MutationObserver подхватывает плитки, догруженные после первого прохода;
5. повторный клик снимает отметку;
6. «Снять отметки» (uncheckAll) обнуляет все отметки и счётчик;
7. кнопка «✕ Снять отметки» в тулбаре есть и активируется по счётчику;
8. выдача Google (udm=2): миниатюры gstatic/googleusercontent без расширения,
   ленивые плитки (src появляется позже — attributes-observer) и шторм
   мутаций не мешают появлению чекбоксов;
9. все 11 поисковиков: шаблон каждой вкладки — страница картинок,
   веб-выдача этих же поисковиков — нет; конечный адрес Mail.ru
   (mail.ru/search?type=images — туда редиректит go.mail.ru) и Google
   на национальных доменах (google.de/co.uk…) считаются выдачей;
10. выдача Brave: прокси-миниатюры imgs.search.brave.com без расширения —
   оригинал распаковывается из base64 пути, иконки-фавиконы отбрасываются;
11. выдача Sogou: плитки img-layout/img-height, картинка в атрибуте drag-img
   (в т.ч. у ленивой плитки без src), оригинал из picurl детальной ссылки;
12. Mail.ru: выдача открыта во вложенном фрейме — инъекция и «Скачать
   отмеченные» работают в дочернем фрейме.

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

    # ---- кнопка «Снять отметки»: window.__IH_CB.uncheckAll() ----
    from app.core.extractor import uncheck_all_selections

    uncheck_all_selections(view.page())
    wait_ms(300)
    count4 = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("uncheckAll обнуляет счётчик", count4 == 0, f"{count4}")

    live = run_js(view.page(), "document.querySelectorAll('.ih-cb input:checked').length")
    check("активных чекбоксов не осталось", live == 0, f"{live}")

    outlined = run_js(view.page(), "document.querySelectorAll('.ih-checked').length")
    check("оранжевая рамка снята со всех плиток", outlined == 0, f"{outlined}")

    got3: dict = {}
    loop3 = QEventLoop()

    def on_sel3(items):
        got3["items"] = items
        loop3.quit()

    _f2(view.page(), on_sel3)
    loop3.exec()
    check("fetch_checked_selections после снятия вернул 0",
          len(got3.get("items", [])) == 0, f"{len(got3.get('items', []))}")

    # одиночная отметка снова работает после массового снятия
    run_js(view.page(), "document.querySelectorAll('.ih-cb')[1].click()")
    wait_ms(200)
    count5 = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("после массового снятия одиночная отметка работает", count5 == 1, f"{count5}")

    # повторный uncheckAll на пустом наборе — безопасен
    uncheck_all_selections(view.page())
    wait_ms(200)
    count6 = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("повторный uncheckAll без отметок безопасен", count6 == 0, f"{count6}")

    view.deleteLater()
    wait_ms(100)

    # ---- кнопка «✕ Снять отметки» в тулбаре WebSearch (UI-проводка) ----
    from app.core import i18n
    from app.ui.web_search import WebSearch

    i18n.set_lang("ru")     # тест проверяет русские надписи кнопок
    ws = WebSearch()
    check("кнопка «Снять отметки» есть в тулбаре",
          hasattr(ws, "btn_clear") and ws.btn_clear.text() == "✕ Снять отметки",
          ws.btn_clear.text())
    check("без отметок кнопка выключена", not ws.btn_clear.isEnabled())

    ws._on_poll_result(4)   # как будто на странице отметили 4 плитки
    check("при 4 отметках кнопка включена", ws.btn_clear.isEnabled())
    check("счётчик «(4)» появился на соседних кнопках",
          "4" in ws.btn_checked.text() and "4" in ws.btn_save.text())

    ws.clear_checked()      # страница без чекбоксов: JS — no-op, счётчик обнуляется
    wait_ms(100)
    check("clear_checked обнуляет счётчик и выключает кнопку",
          ws._checked_count == 0 and not ws.btn_clear.isEnabled())
    ws.deleteLater()


def run_ddg_mock_test() -> None:
    """Мок актуальной (2025) выдачи картинок DuckDuckGo.

    DOM DDG 2025: плитка — LI > FIGURE > DIV > IMG, классы хешированные
    (tile--img/serp-item больше нет), якорей в плитке нет, а «оригиналы»
    в u= прокси /iu/ — кеш tse*.mm.bing.net БЕЗ расширения файла.
    Раньше на такой странице чекбоксы не появлялись вовсе: хостом становился
    сам <img> (потомков которого браузер не рисует), а фильтр looksImage
    отбрасывал оригиналы без расширения. Проверяем оба исправления.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui
    from app.ui.web_search import ENGINES, is_image_search_url

    ddg_tpl = next(t for n, t, _s, _c in ENGINES if "DuckDuckGo" in n)
    check("шаблон DDG ведёт на выдачу картинок (iax=images&ia=images)",
          "iax=images&ia=images" in ddg_tpl, ddg_tpl)
    check("is_image_search_url: шаблон вкладки DDG",
          is_image_search_url(ddg_tpl.format("cats")))
    check("is_image_search_url: iax=images&ia=images", is_image_search_url(
        "https://duckduckgo.com/?q=cats&iax=images&ia=images"))
    check("is_image_search_url: ia=images", is_image_search_url(
        "https://duckduckgo.com/?q=cats&ia=images"))
    check("is_image_search_url: старый iar=images (обратная совместимость)",
          is_image_search_url("https://safe.duckduckgo.com/?q=cats&iar=images"))
    check("is_image_search_url: веб-выдача DDG == False", not is_image_search_url(
        "https://duckduckgo.com/?q=cats&ia=web"))
    check("is_image_search_url: чужой сайт с iax=images == False",
          not is_image_search_url("https://evil.example.com/?iax=images"))

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mock_serp_ddg.html")
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    check("мок DDG загрузился", load_page(view, f"file://{mock}"))

    inject_checkbox_ui(view.page())
    wait_ms(900)

    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("чекбоксы на всех 3 плитках нового DOM DDG", n_boxes == 3,
          f"найдено: {n_boxes}")

    in_img = run_js(view.page(), "document.querySelectorAll('img .ih-cb').length")
    check("чекбокс никогда не внутри <img> (не рисуется)", in_img == 0,
          f"внутри img: {in_img}")

    hosted = run_js(view.page(), """
        [...document.querySelectorAll('.ih-cb')].every((cb) => {
          const host = cb.closest('.ih-cb-host') || cb.parentElement;
          return !!(host && host.querySelector('img'));
        })
    """)
    check("хост каждой галочки содержит свою картинку", hosted is True, f"{hosted}")

    plain = run_js(view.page(), """
        (() => {
          const a = [...document.querySelectorAll('a')]
            .find((x) => x.href.startsWith('https://example.com/some/page'));
          return a ? !!a.querySelector('.ih-cb') : null;
        })()
    """)
    check("веб-ссылка без чекбокса", plain is False, f"{plain}")

    run_js(view.page(), CLICK_ALL_JS)
    wait_ms(200)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("счётчик отмеченных == 3", count == 3, f"{count}")

    got: dict = {}
    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    bests = {it["best"] for it in got.get("items", [])}
    expected = {
        # кеш Bing без расширения — принят благодаря force-раскрытию u=
        "https://tse1.mm.bing.net/th/id/OIP.a1b2c3?pid=ImgDet&w=474&h=474",
        "https://tse4.mm.bing.net/th/id/OIP.9x8y7z?w=300",
        "https://ddgsite-two.com/pic2.jpg",
    }
    check("оригиналы из u= прокси DDG раскрыты верно (в т.ч. без расширения)",
          bests == expected,
          f"лишние: {bests - expected}; не хватает: {expected - bests}")

    view.deleteLater()
    wait_ms(100)


def run_google_mock_test() -> None:
    """Мок актуальной выдачи картинок Google (udm=2).

    Раньше на такой странице чекбоксы появлялись поздно и не на всех
    плитках:
    1. debounce наблюдателя «откладывался» штормом мутаций, которым Google
       дорисовывает выдачу, — скан выполнялся только после паузы;
    2. ленивые плитки получают src ПОЗЖЕ отрисовки — смену атрибута
       childList-observer не видел;
    3. миниатюры gstatic/googleusercontent без расширения отбрасывались
       looksImage — у плиток без якоря imgurl не оставалось кандидатов;
    4. Google регулярно меняет хешированные классы плиток: когда селектор
       перестаёт совпадать, хостом становится голый <img>, и оригинал из
       якоря-соседа не попадает в кандидаты — теперь хост поднимается до
       обёртки, знающей оригинал (подъём хоста по качеству кандидата).
    Проверяем все четыре исправления.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mock_serp_google.html")
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    check("мок Google загрузился", load_page(view, f"file://{mock}"))

    inject_checkbox_ui(view.page())
    wait_ms(900)

    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("чекбоксы на первых 3 плитках Google", n_boxes == 3, f"найдено: {n_boxes}")

    in_img = run_js(view.page(), "document.querySelectorAll('img .ih-cb').length")
    check("чекбокс никогда не внутри <img>", in_img == 0, f"внутри img: {in_img}")

    plain = run_js(view.page(), """
        (() => {
          const a = [...document.querySelectorAll('a')]
            .find((x) => x.href.startsWith('https://example.com/some/page'));
          return a ? !!a.querySelector('.ih-cb') : null;
        })()
    """)
    check("веб-ссылка без чекбокса", plain is False, f"{plain}")

    run_js(view.page(), CLICK_ALL_JS)
    wait_ms(200)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("счётчик отмеченных == 3", count == 3, f"{count}")

    got: dict = {}
    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    bests = {it["best"] for it in got.get("items", [])}
    expected = {
        "https://example-parts.com/pic1.jpg",                  # imgurl якоря
        "https://lh3.googleusercontent.com/pw/ABFCqux7dZm0w=s500",  # миниатюра без расширения
        "https://example-parts.com/pic5.jpg",                  # imgurl через подъём хоста
    }
    check("оригиналы: imgurl, googleusercontent, подъём хоста",
          bests == expected,
          f"лишние: {bests - expected}; не хватает: {expected - bests}")

    # --- шторм мутаций (отрисовка выдачи): скан не должен откладываться ---
    run_js(view.page(), """
        window.__storm = setInterval(() => {
          document.getElementById('storm').appendChild(document.createElement('div'));
        }, 30);
    """)
    wait_ms(300)
    run_js(view.page(), """
        (() => {
          const d = document.createElement('div');
          d.className = 'tile';
          d.innerHTML = '<a href="https://www.google.com/imgres?imgurl=' +
            'https%3A%2F%2Fexample-parts.com%2Fpic4.jpg&amp;docid=X4">' +
            '<img src="https://encrypted-tbn1.gstatic.com/images?q=tbn:late1&amp;s"></a>';
          document.body.insertBefore(d, document.getElementById('storm'));
        })()
    """)
    wait_ms(1600)   # шторм ещё идёт — при debounce плитка была бы непомеченной
    n_storm = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("плитка, добавленная во время шторма мутаций, получила чекбокс",
          n_storm == 4, f"найдено: {n_storm}")
    run_js(view.page(), "clearInterval(window.__storm)")

    # --- ленивая плитка: src появляется позже отрисовки ---
    run_js(view.page(), "document.getElementById('late-img').src = "
          "'https://encrypted-tbn2.gstatic.com/images?q=tbn:late2&s'")
    wait_ms(1600)   # смену атрибута подхватывает attributes-observer
    n_late = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("ленивая плитка (поздний src) получила чекбокс", n_late == 5,
          f"найдено: {n_late}")

    got2: dict = {}
    loop2 = QEventLoop()

    def on_sel2(items):
        got2["items"] = items
        loop2.quit()

    run_js(view.page(), CLICK_UNCHECKED_JS)   # только непомеченные: CLICK_ALL снял бы старые отметки
    wait_ms(200)
    from app.core.extractor import fetch_checked_selections as _fg
    _fg(view.page(), on_sel2)
    loop2.exec()
    bests2 = {it["best"] for it in got2.get("items", [])}
    expected2 = expected | {
        "https://example-parts.com/pic4.jpg",
        "https://encrypted-tbn2.gstatic.com/images?q=tbn:late2&s",
    }
    check("все 4 плитки отмечены, миниатюра gstatic — «лучший» кандидат",
          bests2 == expected2,
          f"лишние: {bests2 - expected2}; не хватает: {expected2 - bests2}")

    view.deleteLater()
    wait_ms(100)


def run_engines_test() -> None:
    """Все 11 поисковиков: шаблон вкладки — выдача картинок, веб-выдача — нет."""
    from app.ui.web_search import ENGINES, is_image_search_url

    check("поисковиков 11", len(ENGINES) == 11, str(len(ENGINES)))
    check("Yahoo и Ecosia убраны из списка",
          not any("Yahoo" in n or "Ecosia" in n for n, _t, _s, _c in ENGINES))
    check("короткие имена вкладок уникальны (нужны для восстановления)",
          len({e[2] for e in ENGINES}) == len(ENGINES))
    check("полные имена уникальны (ключ настроек)",
          len({e[0] for e in ENGINES}) == len(ENGINES))
    for name, tpl, _short, color in ENGINES:
        check(f"шаблон — страница картинок: {name}",
              is_image_search_url(tpl.format("cats")) and color.startswith("#"),
              tpl)

    # Mail.ru объединил портал: go.mail.ru/search_images редиректит на
    # mail.ru/search?...&type=images (выдача — фрейм Яндекса внутри) —
    # конечный адрес обязан считаться выдачей, иначе чекбоксов не будет;
    # Google мигрирует между национальными доменами — udm=2 принимаем
    # с любого google.*
    positives = [
        "https://mail.ru/search?text=cats&type=images",
        "https://mail.ru/search?autologin=no&text=cats&mstatid=&type=images&q=cats",
        "https://www.google.co.uk/search?q=cats&udm=2",
        "https://www.google.de/search?q=cats&udm=2&hl=ru",
    ]
    for u in positives:
        check(f"выдача картинок: {u}", is_image_search_url(u), u)

    negatives = [
        "https://www.google.com/search?q=cats",            # веб-выдача Google
        "https://search.brave.com/search?q=cats",
        "https://www.mojeek.com/web?q=cats",
        "https://www.startpage.com/sp/search?query=cats",  # без cat=images
        "https://search.naver.com/search.naver?where=web&query=cats",
        "https://www.baidu.com/s?wd=cats",
        "https://www.sogou.com/web?query=cats",
        "https://go.mail.ru/search?q=cats",
        "https://mail.ru/search?text=cats",                # веб-поиск Mail.ru (без type=images)
        "https://mail.ru/",                                # портал без поиска
        "https://example.com/?q=cats",
        # поисковики, убранные из списка: страницы картинок больше не считаются
        "https://images.search.yahoo.com/search/images?p=cats",
        "https://www.ecosia.org/images?q=cats",
    ]
    for u in negatives:
        check(f"не выдача картинок: {u}", not is_image_search_url(u), u)


def run_brave_mock_test() -> None:
    """Мок актуальной выдачи картинок Brave (SvelteKit).

    Раньше чекбоксов не было вовсе: плитка — BUTTON.image-result (не якорь),
    а миниатюра — прокси imgs.search.brave.com/<sig>/rs:fit:…/g:ce/<base64>
    БЕЗ расширения — looksImage её отбрасывал, кандидаты пусты.
    Теперь: (1) селектор button.image-result; (2) настоящий оригинал
    распаковывается из base64 в пути прокси; (3) иконки-фавиконы
    (payload ведёт на favicons.search.brave.com) отбрасываются целиком.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mock_serp_brave.html")
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    check("мок Brave загрузился", load_page(view, f"file://{mock}"))

    inject_checkbox_ui(view.page())
    wait_ms(900)

    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("чекбоксы на обеих плитках Brave", n_boxes == 2, f"найдено: {n_boxes}")

    in_btn = run_js(view.page(), "document.querySelectorAll('button .ih-cb').length")
    check("чекбоксы внутри плиток button.image-result", in_btn == 2, f"{in_btn}")

    plain = run_js(view.page(), """
        (() => {
          const a = [...document.querySelectorAll('a')]
            .find((x) => x.href.startsWith('https://example.com/some/page'));
          return a ? !!a.querySelector('.ih-cb') : null;
        })()
    """)
    check("веб-ссылка без чекбокса", plain is False, f"{plain}")

    run_js(view.page(), CLICK_ALL_JS)
    wait_ms(200)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("счётчик отмеченных == 2", count == 2, f"{count}")

    got: dict = {}
    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    bests = {it["best"] for it in got.get("items", [])}
    expected = {
        "https://example.org/brave1.jpg",      # распакован из base64 пути
        "https://parts-site.com/brave2.png",   # распакован из base64 пути
    }
    check("оригиналы Brave распакованы, фавикон отброшен", bests == expected,
          f"лишние: {bests - expected}; не хватает: {expected - bests}")

    view.deleteLater()
    wait_ms(100)


def run_sogou_mock_test() -> None:
    """Мок актуальной выдачи картинок Sogou (Vue SPA).

    Раньше чекбоксов не было вовсе: плитка — DIV.img-layout > A.img-height
    (классов serp-item/tile нет), а настоящая картинка — в атрибуте
    drag-img; у ленивой плитки <img> ещё без src. Теперь: (1) селекторы
    img-layout/img-height; (2) drag-img/data-img берутся как кандидаты;
    (3) оригинал из picurl детальной ссылки побеждает миниатюру.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    from app.core.extractor import fetch_checked_selections, inject_checkbox_ui

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mock_serp_sogou.html")
    app = QApplication.instance() or QApplication([])
    view = QWebEngineView()

    check("мок Sogou загрузился", load_page(view, f"file://{mock}"))

    inject_checkbox_ui(view.page())
    wait_ms(900)

    n_boxes = run_js(view.page(), "document.querySelectorAll('.ih-cb input').length")
    check("чекбоксы на обеих плитках Sogou", n_boxes == 2, f"найдено: {n_boxes}")

    plain = run_js(view.page(), """
        (() => {
          const a = [...document.querySelectorAll('a')]
            .find((x) => x.href.startsWith('https://example.com/some/page'));
          return a ? !!a.querySelector('.ih-cb') : null;
        })()
    """)
    check("веб-ссылка без чекбокса", plain is False, f"{plain}")

    run_js(view.page(), CLICK_ALL_JS)
    wait_ms(200)
    count = run_js(view.page(), "window.__IH_CB_COUNT || 0")
    check("счётчик отмеченных == 2", count == 2, f"{count}")

    got: dict = {}
    loop = QEventLoop()

    def on_sel(items):
        got["items"] = items
        loop.quit()

    fetch_checked_selections(view.page(), on_sel)
    loop.exec()
    bests = {it["best"] for it in got.get("items", [])}
    expected = {
        # у первой плитки оригинала нет в ссылке — лучшая это drag-img
        "https://img02.sogoucdn.com/app/a/100520093/thumb1.jpg",
        # у второй из picurl побеждает настоящий оригинал (ленивая плитка без src)
        "https://orig-site.ru/big2.jpg",
    }
    check("drag-img и picurl-оригинал распознаны", bests == expected,
          f"лишние: {bests - expected}; не хватает: {expected - bests}")

    view.deleteLater()
    wait_ms(100)


def run_frame_mock_test() -> None:
    """Mail.ru: выдача во вложенном фрейме — чекбоксы и «Скачать отмеченные».

    mail.ru/search?type=images (сейчас именно туда редиректит
    go.mail.ru/search_images) не содержит плиток: выдача — вложенный фрейм
    yandex.ru/images/search. Раньше инъекция шла только в главную страницу,
    а в 0.7.x гейт по главному URL (mail.ru/search — не выдача) и вовсе
    блокировал инъекцию — чекбоксов не было вовсе. Проверяем: инъекция
    доходит до дочернего фрейма, а сбор отмеченных (_gather_serp) забирает
    их именно оттуда.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication

    from app.core import i18n
    from app.ui import web_search as wsm
    from app.ui.web_search import WebSearch

    mock = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mock_serp_mailru.html")
    app = QApplication.instance() or QApplication([])
    i18n.set_lang("ru")

    # file://-URL мока не страница поисковика — подменяем проверку на True,
    # сам механизм выбора фреймов (_serp_frames) остаётся боевым
    orig_check = wsm.is_image_search_url
    wsm.is_image_search_url = lambda url: True
    try:
        ws = WebSearch()
        got: dict = {}

        def on_found(urls, referer):
            got["urls"] = urls

        ws.images_found.connect(on_found)
        check("мок Mail.ru (обёртка + фрейм) загрузился",
              load_page(ws.view, f"file://{mock}", wait_ms_after=2200))

        main_boxes = run_js(ws.view.page(),
                            "document.querySelectorAll('.ih-cb input').length")
        check("в обёртке Mail.ru чекбоксов нет (плиток там нет)",
              main_boxes == 0, f"{main_boxes}")

        child = ws.view.page().mainFrame().children()[0]
        child_boxes = run_js(child,
                             "document.querySelectorAll('.ih-cb input').length")
        check("инъекция дошла до вложенного фрейма (2 плитки)",
              child_boxes == 2, f"{child_boxes}")

        run_js(child, CLICK_ALL_JS)
        wait_ms(200)
        child_count = run_js(child, "window.__IH_CB_COUNT || 0")
        check("обе плитки фрейма отмечены", child_count == 2, f"{child_count}")

        ws.download_checked()
        # ждём сигнал images_found (сбор идёт по обоим фреймам, до 10 с)
        for _ in range(50):
            if "urls" in got:
                break
            wait_ms(200)
        bests = set(got.get("urls", []))
        expected = {
            "https://example.org/frame1.jpg",                              # img_url
            "https://avatars.mds.yandex.net/get-mpic/800/frame_orig2/orig",  # origUrl
        }
        check("«Скачать отмеченные» забрал плитки из фрейма", bests == expected,
              f"лишние: {bests - expected}; не хватает: {expected - bests}")

        ws.deleteLater()
        wait_ms(100)
    finally:
        wsm.is_image_search_url = orig_check


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
        run_engines_test()
        run_mock_test()
        run_ddg_mock_test()
        run_google_mock_test()
        run_brave_mock_test()
        run_sogou_mock_test()
        run_frame_mock_test()

    print()
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} → {FAILURES}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    rc = main()
    os._exit(rc)  # обходим teardown Qt: известные abort'ы при разрушении виджетов в песочнице
