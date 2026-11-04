"""Мост «программа → телефон»: последняя выдача вкладки «Поиск картинок».

Вкладка «Поиск картинок» ищет настоящим браузером (QWebEngineView — целый
Chromium): ей не страшны ни блокировки, ни капчи, ни смена серверных
форматов выдачи, поэтому она видит результаты там, где чистый HTTP-запрос
сервера получает пустую страницу. Этот модуль — простое хранилище без
зависимостей: программа кладёт сюда «очищенные и облегчённые» плитки
последней выдачи (только ссылка на оригинал, превью, заголовок и размеры —
никакого HTML), а веб-интерфейс забирает их поисковиком «Программа»
(движок ``desktop`` в ``/api/web/search``).

Передача автоматическая: программа сама обновляет хранилище после
загрузки страницы выдачи (см. ``app/ui/web_search.py``), телефону ничего
нажимать не нужно — выбрал поисковик «Программа», ввёл тот же запрос (или
любой другой — покажется последняя выдача программы целиком) и увидел
плитки. Хранится только последняя выдача: предыдущие перекрываются новой,
копировать несколько страниц не нужно.

Потокобезопасно: пишет GUI-поток, читают потоки HTTP-сервера.
"""

from __future__ import annotations

import threading
import time

_MAX_TILES = 200
_TILE_KEYS = ("url", "thumb", "title", "w", "h", "source")

_LOCK = threading.Lock()
_STATE: dict = {"query": "", "engine": "", "page_url": "", "ts": 0.0,
                "tiles": []}


def _norm_tile(t: dict) -> dict | None:
    """Оставить чистую плитку: http(s)-ссылка + превью + название + размеры."""
    url = str((t or {}).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    thumb = str(t.get("thumb") or "").strip()
    if not thumb.startswith(("http://", "https://")):
        thumb = url                     # превью нет — плитка покажет оригинал
    try:
        w = max(0, int(t.get("w") or 0))
        h = max(0, int(t.get("h") or 0))
    except (TypeError, ValueError):
        w = h = 0
    title = str(t.get("title") or "").strip()[:150]
    source = str(t.get("source") or "").strip()
    if not source.startswith(("http://", "https://")):
        source = ""
    return {"url": url, "thumb": thumb, "title": title,
            "w": w, "h": h, "source": source}


def update(query: str, engine: str, page_url: str, tiles: list[dict]) -> None:
    """Запомнить выдачу программы (вызывается из вкладки «Поиск картинок»).

    Плитки чистятся, дедуплицируются по превью и обрезаются до
    :data:`_MAX_TILES`; пустой список не затирает предыдущую выдачу —
    страница ещё дорисовывается, последняя удачная порция ценнее пустоты.
    """
    clean: list[dict] = []
    seen: set[str] = set()
    for t in tiles or []:
        tile = _norm_tile(t)
        if tile is None or tile["thumb"] in seen:
            continue
        seen.add(tile["thumb"])
        clean.append(tile)
    if not clean:
        return
    with _LOCK:
        _STATE.update(query=(query or "").strip()[:200],
                      engine=(engine or "").strip()[:40],
                      page_url=(page_url or "").strip()[:500],
                      ts=time.time(),
                      tiles=clean[:_MAX_TILES])


def get() -> dict:
    """Последняя выдача программы: ``{"query","engine","page_url","ts","tiles"}``."""
    with _LOCK:
        st = dict(_STATE)
    tiles = [{k: t[k] for k in _TILE_KEYS} for t in st["tiles"]]
    return {"query": st["query"], "engine": st["engine"],
            "page_url": st["page_url"], "ts": st["ts"], "tiles": tiles}


def is_empty() -> bool:
    """Была ли уже передача (иначе телефону показываем подсказку)."""
    with _LOCK:
        return not _STATE["tiles"]
