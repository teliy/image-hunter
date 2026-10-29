"""Сбор ссылок на изображения со страницы, открытой в QWebEngineView.

Основной инструмент — COLLECT_JS: JavaScript, который выполняется на странице
поисковой выдачи (Яндекс.Картинки, DuckDuckGo, Google, Bing) и собирает:

1. все ``<img>`` (src, srcset, data-атрибуты ленивой загрузки);
2. оригиналы из прокси DuckDuckGo (``external-content.duckduckgo.com/iu/?u=<оригинал>``);
3. ссылки на оригиналы из JSON в атрибутах ``data-bem`` (специфика Яндекса);
4. прямые ссылки на файлы картинок, найденные в сыром HTML страницы
   (в том числе в встроенном JSON выдачи, с раскрытием ``\\u002F`` и ``\\/``).
"""

from __future__ import annotations

import json

COLLECT_JS = r"""
(() => {
  const urls = new Set();

  const decodeJson = (s) => String(s)
    .replace(/\\u002[fF]/g, '/')
    .replace(/\\\//g, '/');

  const push = (raw) => {
    try {
      if (!raw || typeof raw !== 'string' || raw.startsWith('data:')) return;
      const abs = new URL(raw, location.href);
      if (abs.protocol !== 'http:' && abs.protocol !== 'https:') return;
      // Прокси DuckDuckGo: раскрываем оригинальный URL из параметра u=
      if (abs.hostname.endsWith('duckduckgo.com') && abs.pathname.startsWith('/iu')) {
        const orig = abs.searchParams.get('u');
        if (orig) { push(orig); return; }
      }
      urls.add(abs.href);
    } catch (e) {}
  };

  const pushScan = (s) => {
    if (!s) return;
    (decodeJson(s).match(/https?:\/\/[^\s"'<>\\)]+/g) || []).forEach(push);
  };

  // 1. Все <img>
  document.querySelectorAll('img').forEach((im) => {
    push(im.currentSrc || im.src);
    if (im.srcset) push(im.srcset.split(',')[0].trim().split(/\s+/)[0]);
    if (im.dataset) {
      ['src', 'thumb', 'original', 'url', 'lazy-src', 'lazySrc'].forEach((k) => {
        if (im.dataset[k]) push(im.dataset[k]);
      });
    }
  });

  // 2. Яндекс: JSON в атрибуте data-bem (там прячутся ссылки на оригиналы)
  document.querySelectorAll('[data-bem]').forEach((el) => pushScan(el.getAttribute('data-bem')));

  // 3. Анкоры, ведущие прямо на файлы картинок
  document.querySelectorAll('a[href]').forEach((a) => push(a.href));

  // 4. Сканируем сырой HTML: встроенный JSON выдачи содержит прямые ссылки
  pushScan(document.documentElement.outerHTML);

  return JSON.stringify(Array.from(urls).slice(0, 500));
})()
"""

MAX_URLS = 500


def collect_image_urls(page, callback) -> None:
    """Запустить сбор ссылок на странице ``page`` (QWebEnginePage).

    ``callback(list[str])`` будет вызван в GUI-потоке со списком ссылок.
    """
    def _done(result):
        try:
            if isinstance(result, str):
                urls = json.loads(result)
            else:
                urls = list(result or [])
        except Exception:
            urls = []
        # страховка: оставляем только http(s)-строки
        urls = [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]
        callback(urls[:MAX_URLS])

    page.runJavaScript(COLLECT_JS, _done)
