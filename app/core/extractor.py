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

from app.core.i18n import tr

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
      // Прокси Brave: /<подпись>/rs:fit:…/g:ce/<base64 оригинала>
      // (иконки фавиконов favicons.search.brave.com выбрасываем)
      if (abs.hostname === 'imgs.search.brave.com') {
        const pm = abs.pathname.match(/\/g:[a-z]+\/(.+)$/);
        if (pm) {
          try {
            let b64 = pm[1].replace(/\/+/g, '').replace(/-/g, '+').replace(/_/g, '/');
            b64 += '='.repeat((4 - b64.length % 4) % 4);
            const bin = atob(b64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            const orig = new TextDecoder('utf-8').decode(bytes);
            if (/^https?:\/\//i.test(orig)
                && !new URL(orig).hostname.endsWith('favicons.search.brave.com')) {
              push(orig); return;
            }
          } catch (e) {}
        }
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

  // 2b. Sogou: настоящая картинка плитки — в атрибутах drag-img / data-img
  document.querySelectorAll('[drag-img], [data-img]').forEach((el) => {
    push(el.getAttribute('drag-img'));
    push(el.getAttribute('data-img'));
  });

  // 3. Анкоры, ведущие прямо на файлы картинок
  document.querySelectorAll('a[href]').forEach((a) => push(a.href));

  // 4. Сканируем сырой HTML: встроенный JSON выдачи содержит прямые ссылки
  pushScan(document.documentElement.outerHTML);

  return JSON.stringify(Array.from(urls).slice(0, 500));
})()
"""

MAX_URLS = 500


def _noop(_result=None) -> None:
    """Заглушка колбэка для runJavaScript."""


# Последние JS-колбэки: PySide6 не удерживает ссылку на колбэк
# runJavaScript у QWebEngineFrame (у страницы удерживает) — без нашей
# ссылки колбэк собирает сборщик мусора и результат никогда не приходит.
_JS_CBS: list = []


def run_js(target, code: str, callback=None) -> None:
    """Выполнить JS на странице-ИЛИ-фрейме QWebEngine.

    У QWebEnginePage callback не обязателен, у QWebEngineFrame — обязателен:
    всегда передаём колбэк (по умолчанию — заглушку), это работает для обоих.
    """
    cb = callback or _noop
    _JS_CBS.append(cb)
    if len(_JS_CBS) > 64:          # держим последние 64 — больше не нужно
        del _JS_CBS[:32]
    target.runJavaScript(code, cb)


def collect_image_urls(page, callback) -> None:
    """Запустить сбор ссылок на странице ``page`` (QWebEnginePage или фрейм).

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

    run_js(page, COLLECT_JS, _done)


# --------------------------------------------------------------------------
# Чекбоксы на плитках выдачи: отметить нужные — скачать оригиналы.
#
# CHECKBOX_INIT_JS навешивает на каждую плитку поисковой выдачи чекбокс и
# запоминает для неё цепочку ссылок-кандидатов на «большой» файл:
#   1. origUrl из data-bem (Яндекс) — тот самый avatars.mds.yandex.net/get-mpic/…/orig;
#   2. оригинал из параметров ссылок (img_url у Яндекса, u= у DuckDuckGo,
#      imgurl= у Google, murl из JSON-атрибута m= у Bing);
#   3. обычные <img> (последний шанс).
# Отмеченные плитки доступны странице наружу через window.__IH_SEL_JSON
# (JSON-строка вида [{"best": "<url>", "alts": [...]}, …]) и window.__IH_CB_COUNT.
# --------------------------------------------------------------------------

CHECKBOX_INIT_JS = r"""
(() => {
  if (window.__IH_CB) { window.__IH_CB.scan(); return; }

  const ON_DDG = /(^|\.)duckduckgo\.com$/.test(location.hostname);
  const ON_GOOGLE = /(^|\.)google\.[a-z.]{2,6}$/.test(location.hostname);
  const ON_BRAVE = /(^|\.)brave\.com$/.test(location.hostname);
  const ON_SOGOU = /(^|\.)sogou\.com$/.test(location.hostname);
  const ITEM_SEL = [
    '.serp-item', '[class*="serp-item"]', '[class*="SerpItem"]',
    '[class*="SerpList-Item"]',
    '.tile--img', '[class*="tile--img"]',
    '.isv-r', '[data-rid]', '[data-lpage]',
    '.imgpt', '[class*="imgpt"]', '.iusc',
    '[class*="ImageCard"]', '[class*="imageCard"]', '[class*="photo-card"]',
    // DOM DuckDuckGo 2025+: плитка — LI > FIGURE c хешированными классами,
    // селектор структурный, только на доменах DDG (чтобы не зацепить чужие)
    ...(ON_DDG ? ['ol > li > figure', 'figure', 'article'] : []),
    // плитка выдачи картинок Google (udm=2); хешированные классы Google
    // меняются от релиза к релизу — при несовпадении срабатывает fallback
    ...(ON_GOOGLE ? ['.eA0Zlc'] : []),
    // плитка выдачи Brave: BUTTON.image-result с прокси-миниатюрой внутри
    ...(ON_BRAVE ? ['button.image-result'] : []),
    // плитка выдачи Sogou: DIV.img-layout > A.img-height (drag-img = картинка)
    ...(ON_SOGOU ? ['[class*="img-layout"]', '[class*="img-height"]'] : [])
  ].join(',');

  const IMAGE_RE = /\.(jpe?g|png|gif|webp|bmp|avif|jfif|tiff?)([?#]|$)/i;

  // Миниатюры части поисковиков не имеют расширения в URL — без этих
  // шаблонов looksImage отбрасывал бы плитки целиком (чекбоксы «не у всех»).
  const looksImage = (u) =>
    IMAGE_RE.test(u) ||
    /avatars\.mds\.yandex\.net/.test(u) ||
    /\/orig(\/|$|\?)/i.test(u) ||
    /\/iu\//.test(u) ||
    /encrypted-tbn\d*\.gstatic\.com/.test(u) ||   // миниатюры Google (udm=2)
    /\.googleusercontent\.com/.test(u) ||          // прокси-миниатюры Google
    /\.mm\.bing\.net\/th/.test(u) ||               // кеш Bing (и миниатюры Yahoo)
    /\/it\/u=/.test(u) ||                          // миниатюры Baidu (img*.baidu.com/it/u=…)
    /pstatic\.net/.test(u) ||                      // миниатюры Naver (search.pstatic.net)
    /imgs\.search\.brave\.com\//.test(u) ||        // прокси-миниатюры Brave (оригинал в base64 в пути)
    /sogoucdn\.com/.test(u) ||                     // миниатюры Sogou (img*.sogoucdn.com)
    /pic\.sogou\.com/.test(u);                     // миниатюры/детальные ссылки Sogou

  // --- data-state (новый UI Яндекса): JSON всего SERP'а в атрибуте Root'а ---
  const STATE = new Map(); // url или origin+pathname -> origUrl
  const normKey = (u) => {
    try { const x = new URL(u, location.href); return x.origin + x.pathname; }
    catch (e) { return u; }
  };
  let lastStateSrc = '';
  const buildState = () => {
    const els = [...document.querySelectorAll('[data-state]')];
    const src = els.map((e) => e.getAttribute('data-state')).join('|').length
      + ':' + (els[0] ? els[0].getAttribute('data-state').slice(0, 200) : '');
    if (src === lastStateSrc && STATE.size) return;
    lastStateSrc = src;
    STATE.clear();
    els.forEach((el) => {
      let data;
      try { data = JSON.parse(el.getAttribute('data-state')); } catch (e) { return; }
      const gather = (o, orig) => {
        if (typeof o === 'string') {
          if (/^https?:\/\//.test(o)) { STATE.set(o, orig); STATE.set(normKey(o), orig); }
        } else if (Array.isArray(o)) o.forEach((v) => gather(v, orig));
        else if (o && typeof o === 'object') Object.values(o).forEach((v) => gather(v, orig));
      };
      const visit = (obj) => {
        if (!obj || typeof obj !== 'object') return;
        if (Array.isArray(obj)) { obj.forEach(visit); return; }
        if (typeof obj.origUrl === 'string' && /^https?:/.test(obj.origUrl)) {
          gather(obj, obj.origUrl); // все url этого элемента выдачи ведут к его оригиналу
        } else {
          Object.values(obj).forEach(visit);
        }
      };
      visit(data);
    });
  };

  // Кандидаты-«оригиналы» внутри одного элемента выдачи.
  const collectCandidates = (root) => {
    const out = [];
    const seen = new Map();
    // root и его потомки: querySelectorAll не видит атрибуты самого root
    const selfAndDesc = (sel) => {
      const res = [];
      if (root.matches && root.matches(sel)) res.push(root);
      res.push(...root.querySelectorAll(sel));
      return res;
    };
    const add = (raw, score, force) => {
      try {
        if (!raw || typeof raw !== 'string' || raw.startsWith('data:')) return;
        const abs = new URL(raw, location.href);
        if (abs.protocol !== 'http:' && abs.protocol !== 'https:') return;
        // Прокси DuckDuckGo: раскрываем оригинал из параметра u=.
        // Принимаем его всегда (force): у выдачи DDG оригинал часто без
        // расширения (кеш tse*.mm.bing.net/th/id/…), но это заведомо картинка.
        if (abs.hostname.endsWith('duckduckgo.com') && abs.pathname.startsWith('/iu')) {
          const orig = abs.searchParams.get('u');
          if (orig) { add(orig, Math.max(score, 85), true); return; }
        }
        // Прокси Brave: /<подпись>/rs:fit:…/g:ce/<base64 оригинала> —
        // настоящий URL зашит в путь, расширения нет. Иконки фавиконов
        // (payload ведёт на favicons.search.brave.com) выбрасываем целиком.
        if (abs.hostname === 'imgs.search.brave.com') {
          const pm = abs.pathname.match(/\/g:[a-z]+\/(.+)$/);
          if (pm) {
            try {
              let b64 = pm[1].replace(/\/+/g, '').replace(/-/g, '+').replace(/_/g, '/');
              b64 += '='.repeat((4 - b64.length % 4) % 4);
              const bin = atob(b64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
              const orig = new TextDecoder('utf-8').decode(bytes);
              if (/^https?:\/\//i.test(orig)) {
                if (new URL(orig).hostname.endsWith('favicons.search.brave.com')) return;
                add(orig, Math.max(score, 85), true);
                return;
              }
            } catch (e) {}
          }
        }
        if (!force && !looksImage(abs.href)) return;
        if (seen.has(abs.href)) {
          const prev = seen.get(abs.href);
          if (score > prev.s) prev.s = score;
          return;
        }
        const rec = { u: abs.href, s: score };
        seen.set(abs.href, rec);
        out.push(rec);
      } catch (e) {}
    };

    // 1. Яндекс: JSON в data-bem (origUrl — большой файл)
    selfAndDesc('[data-bem]').forEach((el) => {
      let data;
      try { data = JSON.parse(el.getAttribute('data-bem')); } catch (e) { return; }
      const walk = (obj, key) => {
        if (typeof obj === 'string') {
          let sc = 0;
          if (key && /orig/i.test(key)) sc = 100;
          else if (key && /(preview|thumb|small)/i.test(key)) sc = 15;
          else if (key) sc = 60;
          add(obj, sc);
        } else if (Array.isArray(obj)) {
          obj.forEach((v) => walk(v, key));
        } else if (obj && typeof obj === 'object') {
          Object.entries(obj).forEach(([k, v]) => walk(v, k));
        }
      };
      walk(data, '');
    });

    // 1b. Sogou: настоящая картинка плитки — в атрибутах drag-img / data-img
    // (img рендерится директивой v-lazy и может ещё не иметь src).
    // Без гейта по хосту: на мок-страницах hostname пуст, а drag-img вне
    // Sogou почти не встречается; data-img принимаем только «похожим на
    // картинку», чтобы не тащить мусор с чужих сайтов.
    selfAndDesc('[drag-img], [data-img]').forEach((el) => {
      ['drag-img', 'data-img'].forEach((k) => {
        const v = el.getAttribute(k);
        if (v && /^https?:/i.test(v)) add(v, 75, k === 'drag-img');
      });
    });

    // 2. Ссылки-плитки: оригиналы в параметрах (Яндекс, Google, DuckDuckGo…)
    selfAndDesc('a[href]').forEach((a) => {
      try {
        const abs = new URL(a.href, location.href);
        const p = abs.searchParams;
        // Параметры-оригиналы поисковиков — картинки по определению (force:
        // у них бывает URL без расширения — кеш Bing у DDG и т.п.).
        // piurl — прокси Startpage, mediaurl — детальные ссылки Yahoo/Bing,
        // picurl — детальные ссылки Sogou; url/du — общие, только если похоже
        // на картинку (force=false)
        [['img_url', 80, true], ['imgurl', 80, true], ['murl', 80, true],
         ['u', 85, true], ['piurl', 80, true], ['mediaurl', 80, true],
         ['picurl', 80, true], ['du', 75, false], ['url', 70, false]]
          .forEach(([k, sc, force]) => {
            const v = p.get(k);
            if (v && /^https?:/i.test(v)) add(v, sc, force);
          });
        // Bing: JSON в атрибуте m=
        const m = a.getAttribute('m');
        if (m && m.trim().startsWith('{')) {
          try {
            const j = JSON.parse(m);
            if (j && typeof j.murl === 'string') add(j.murl, 85, true);
          } catch (e) {}
        }
        add(a.href, 25); // прямая ссылка на файл тоже кандидат
      } catch (e) {}
    });

    // 3. Обычные <img> и background-image — последний шанс
    selfAndDesc('img').forEach((im) => {
      add(im.currentSrc || im.src, 10);
      (im.srcset || '').split(',').forEach((part) => {
        const u = part.trim().split(/\s+/)[0];
        if (u) add(u, 12);
      });
    });
    selfAndDesc('[style*="background"]').forEach((el) => {
      const st = el.getAttribute('style') || '';
      const re = /background-image:\s*url\((['"]?)([^)'"]+)\1\)/gi;
      let m;
      while ((m = re.exec(st)) !== null) add(m[2], 10);
    });

    // 4. Подстановка оригиналов из data-state: миниатюра -> её origUrl
    const extra = [];
    out.forEach((rec) => {
      const orig = STATE.get(rec.u) || STATE.get(normKey(rec.u));
      if (orig && !seen.has(orig)) {
        const ins = { u: orig, s: rec.s + 50 };
        seen.set(orig, ins);
        extra.push(ins);
      }
    });
    out.push(...extra);

    out.forEach((rec) => { if (/\/orig(\/|$|\?)/i.test(rec.u)) rec.s += 15; });
    out.sort((a, b) => b.s - a.s);
    return out.map((rec) => rec.u);
  };

  const SEL = new Map(); // элемент-плитка -> { cands, cb, input, checked }

  const refresh = () => {
    const arr = [];
    SEL.forEach((rec) => {
      if (rec.checked) arr.push({ best: rec.cands[0], alts: rec.cands.slice(1, 5) });
    });
    window.__IH_CB_COUNT = arr.length;
    window.__IH_SEL_JSON = JSON.stringify(arr);
  };

  const attach = (host, cands) => {
    try {
      // Чекбокс нельзя вставлять внутрь замещаемых элементов (<img>, <picture>)
      // — браузер никогда не рисует их потомков, галочка была бы невидима.
      // Используем родителя (новый DOM DDG даёт хостом именно сам <img>).
      while (host && (host.tagName === 'IMG' || host.tagName === 'PICTURE')) {
        host = host.parentElement;
      }
      if (!host || host === document.body || host === document.documentElement) return;
      const pos = getComputedStyle(host).position;
      if (!pos || pos === 'static') host.classList.add('ih-cb-host');
      const cb = document.createElement('label');
      cb.className = 'ih-cb';
      cb.title = __IH_CB_TITLE__;
      const input = document.createElement('input');
      input.type = 'checkbox';
      const box = document.createElement('span');
      box.className = 'ih-cb-box';
      cb.appendChild(input);
      cb.appendChild(box);
      const toggle = () => {
        input.checked = !input.checked;
        const rec = SEL.get(host);
        if (rec) {
          rec.checked = input.checked;
          host.classList.toggle('ih-checked', input.checked);
          refresh();
        }
      };
      ['mousedown', 'mouseup', 'dblclick', 'contextmenu'].forEach((t) => {
        cb.addEventListener(t, (e) => e.stopPropagation());
      });
      cb.addEventListener('click', (e) => {
        // preventDefault гасит и переход по ссылке-плитке, и нативный toggle:
        e.preventDefault();
        e.stopPropagation();
        toggle();
      });
      host.appendChild(cb);
      SEL.set(host, { cands, best: cands[0], cb, input, checked: false });
    } catch (e) {}
  };

  const scan = () => {
    buildState();
    // подчистить плитки, исчезнувшие со страницы
    SEL.forEach((rec, host) => {
      if (!document.documentElement.contains(host)) {
        SEL.delete(host);
        refresh();
      }
    });
    const roots = new Set();
    document.querySelectorAll('a[href], [data-bem], img, [style*="background-image"]')
      .forEach((el) => {
        const host = el.closest(ITEM_SEL) || el;
        roots.add(host);
      });
    roots.forEach((host) => {
      if (host.dataset.ihCbDone === 'ok') return;
      // не вешаем чекбокс на всю страницу или общий контейнер плиток
      if (host === document.body || host === document.documentElement) {
        host.dataset.ihCbDone = 'skip';
        return;
      }
      const matched = host.matches && host.matches(ITEM_SEL);
      if (!matched && host.querySelectorAll(ITEM_SEL).length > 0) {
        host.dataset.ihCbDone = 'skip'; // внутри есть нормальные плитки — это обёртка
        return;
      }
      if (!matched) {
        // случайный внутренний элемент: не дублируем чекбокс той же картинке
        let dup = false;
        SEL.forEach((rec, h) => {
          if (h === host) return;
          if (h.contains(host) || host.contains(h)) dup = true;
        });
        if (dup) { host.dataset.ihCbDone = 'dup'; return; }
      }
      const cands = collectCandidates(host);
      if (!cands.length) { delete host.dataset.ihCbDone; return; } // ленивые картинки — попробуем позже
      if (!matched) {
        let same = false;
        SEL.forEach((rec, h) => {
          if (h !== host && !h.contains(host) && !host.contains(h) && rec.cands[0] === cands[0]) same = true;
        });
        if (same) { host.dataset.ihCbDone = 'dup'; return; }
      }
      host.dataset.ihCbDone = 'ok';
      attach(host, cands);
    });
    refresh();
  };

  // Стили чекбоксов. ВАЖНО: страница-выдача может быть в любой момент
  // заменена (ошибка сети, переадресация) — document.head и даже
  // documentElement бывают null, и незащищённый appendChild падал
  // «Uncaught TypeError», оставаясь в консоли вкладки. Всё под защитой.
  const injectStyle = () => {
    try {
      if (document.getElementById('ih-cb-style')) return;
      const root = document.head || document.documentElement;
      if (!root) return;      // документ ещё грузится/заменяется — стили поставит следующий скан
      const st = document.createElement('style');
      st.id = 'ih-cb-style';
      st.textContent = [
        '.ih-cb{position:absolute!important;top:8px;left:8px;z-index:2147483640;',
        'width:26px;height:26px;margin:0;cursor:pointer;display:block;filter:drop-shadow(0 1px 3px rgba(0,0,0,.45));}',
        '.ih-cb input{position:absolute;opacity:0;width:100%;height:100%;margin:0;cursor:pointer;}',
        '.ih-cb .ih-cb-box{position:absolute;inset:0;border-radius:7px;',
        'background:rgba(255,255,255,.93);border:2px solid #ff7a1a;}',
        '.ih-cb:hover .ih-cb-box{background:#fff;}',
        '.ih-cb .ih-cb-box::after{content:\'\';position:absolute;left:7px;top:2px;width:6px;height:12px;',
        'border:solid #fff;border-width:0 3px 3px 0;transform:rotate(45deg);opacity:0;}',
        '.ih-cb input:checked + .ih-cb-box{background:#ff7a1a;}',
        '.ih-cb input:checked + .ih-cb-box::after{opacity:1;}',
        '.ih-cb-host{position:relative!important;}',
        '.ih-checked{outline:3px solid #ff7a1a!important;outline-offset:-3px;border-radius:6px;}'
      ].join('');
      root.appendChild(st);
    } catch (e) {}
  };

  // массовое снятие отметок (кнопка «Снять отметки» на тулбаре)
  const uncheckAll = () => {
    SEL.forEach((rec, host) => {
      rec.input.checked = false;
      rec.checked = false;
      host.classList.remove('ih-checked');
    });
    refresh();
  };

  window.__IH_CB = { scan, uncheckAll };

  try { injectStyle(); scan(); } catch (e) {}   // документ может быть mid-teardown

  // Подхватывать плитки, догружаемые при прокрутке (бесконечная выдача).
  // ТРОТТЛИНГ, а не debounce: при шторме мутаций (Google дорисовывает выдачу
  // несколько секунд подряд) debounce всё время откладывал скан до паузы —
  // чекбоксы появлялись поздно и не на всех плитках. Троттлинг гарантирует
  // скан не позже 400 мс после ПЕРВОЙ мутации шторма.
  // attributes+['src']: у ленивых плиток <img> получает src позже — childList
  // смену атрибута не видит, поэтому на части плиток чекбоксов не было вовсе.
  let lastScan = 0, pend = 0, mo = null, observed = null;
  const schedule = () => {
    clearTimeout(pend);
    const wait = Math.max(0, lastScan + 400 - Date.now());
    pend = setTimeout(() => { lastScan = Date.now(); scan(); }, wait);
  };
  const startObserver = () => {
    const b = document.body || document.documentElement;
    if (!b || b === observed) return;
    if (!mo) {
      mo = new MutationObserver(schedule);
      // страховка: раз в 2 с перепроверяем тело и пересканируем — чинит
      // случаи, когда выдача дорисовалась «тихо» (без мутаций observer'а)
      setInterval(() => { startObserver(); schedule(); }, 2000);
    }
    mo.observe(b, { childList: true, subtree: true,
                    attributes: true, attributeFilter: ['src'] });
    observed = b;
  };
  if (document.body) { lastScan = Date.now(); startObserver(); }
  else document.addEventListener('DOMContentLoaded', startObserver);
})()
"""


def inject_checkbox_ui(page) -> None:
    """Навесить чекбоксы выбора на плитки выдачи (идемпотентно, с observer'ом).

    ``page`` — QWebEnginePage или QWebEngineFrame (Mail.ru показывает выдачу
    во вложенном фрейме). Подсказка чекбокса локализуется на стороне Python
    (tr) и подставляется в JS как готовый JSON-литерал.
    """
    run_js(page, CHECKBOX_INIT_JS.replace("__IH_CB_TITLE__", json.dumps(tr("ws.cb_title"))))


def rescan_checkbox_ui(page) -> None:
    """Повторный проход по странице (после поздней отрисовки плиток)."""
    run_js(page, "window.__IH_CB && window.__IH_CB.scan()")


def uncheck_all_selections(page) -> None:
    """Снять все отметки с плиток выдачи на странице ``page``."""
    run_js(
        page,
        "window.__IH_CB && window.__IH_CB.uncheckAll"
        " ? window.__IH_CB.uncheckAll() : 0",
    )


def fetch_checked_selections(page, callback) -> None:
    """Доставить отмеченные плитки: ``callback([{best: url, alts: [...]}, …])``."""
    def _done(result):
        try:
            if isinstance(result, str):
                items = json.loads(result)
            else:
                items = list(result or [])
        except Exception:
            items = []
        clean = []
        for it in items:
            if not isinstance(it, dict):
                continue
            best = it.get("best")
            if isinstance(best, str) and best.startswith(("http://", "https://")):
                alts = [u for u in (it.get("alts") or [])
                        if isinstance(u, str) and u.startswith(("http://", "https://"))]
                clean.append({"best": best, "alts": alts})
        callback(clean)

    run_js(page, "window.__IH_SEL_JSON || '[]'", _done)
