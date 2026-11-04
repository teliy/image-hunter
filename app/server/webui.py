"""Мобильный веб-интерфейс Image Hunter — одна страница без внешних файлов.

``PAGE`` — вся страница (HTML + CSS + JS в одном файле): лента папки с
миниатюрами, поиск, полный просмотр со свайпами, переименование, удаление,
удаление фона, журнал. Никаких CDN — страница работает в локальной сети
без интернета. Токен берётся из адреса (``?token=``), запоминается в
localStorage и подставляется во все запросы и адреса картинок из JS —
сервер не подставляет ничего, страница статична.

Язык — русский и английский (переключатель, автовыбор по языку браузера).

``PAGE_401`` — страница «нужен токен», которую сервер отдаёт вместо
интерфейса тому, кто пришёл без токена.
"""

PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#171a21">
<title>Image Hunter</title>
<style>
:root{
  --bg:#171a21;--bg2:#1e2430;--line:#2c3546;--text:#e8edf5;--muted:#9aa5b5;
  --accent:#569cd6;--danger:#e05656;--ok:#3fb27f;--radius:12px;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;
  min-height:100vh;overscroll-behavior-y:contain}
button{font:inherit;color:inherit;background:none;border:none;cursor:pointer}
input{font:inherit}
header{position:sticky;top:0;z-index:5;background:rgba(23,26,33,.96);
  border-bottom:1px solid var(--line);padding:calc(env(safe-area-inset-top) + 8px) 12px 8px}
.hrow{display:flex;align-items:center;gap:8px}
.hrow h1{font-size:17px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.hbtn{padding:7px 10px;border-radius:9px;background:var(--bg2);border:1px solid var(--line);font-size:14px}
.hbtn:active{background:#28324a}
#crumbs{margin-top:8px;display:flex;align-items:center;gap:4px;overflow-x:auto;
  white-space:nowrap;font-size:13.5px;color:var(--muted);scrollbar-width:none}
#crumbs::-webkit-scrollbar{display:none}
#crumbs a{color:var(--accent);text-decoration:none;padding:3px 2px;flex-shrink:0}
#crumbs .sep{color:var(--muted);flex-shrink:0}
#crumbs .here{color:var(--text);padding:3px 2px}
.srow{display:flex;gap:8px;margin-top:8px}
#q{flex:1;background:var(--bg2);border:1px solid var(--line);border-radius:10px;
  color:var(--text);padding:9px 12px;outline:none}
#q:focus{border-color:var(--accent)}
.chk{display:flex;align-items:center;gap:5px;font-size:13px;color:var(--muted);
  background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:0 10px}
.chk input{accent-color:var(--accent)}
.sel{background:var(--bg2);border:1px solid var(--line);border-radius:10px;
  color:var(--text);padding:9px 6px;outline:none;max-width:132px}
.sel:focus{border-color:var(--accent)}
.hbtn.on{border-color:var(--accent);color:var(--accent)}
.ckb{position:absolute;top:4px;left:4px;width:28px;height:28px;border-radius:9px;
  background:rgba(23,26,33,.85);border:1px solid var(--line);font-size:14px;line-height:1.3}
.ckb.on{background:var(--accent);color:#0c0e13;border-color:var(--accent)}
#wfab{position:fixed;right:14px;bottom:calc(env(safe-area-inset-bottom) + 18px);z-index:30;
  background:var(--accent);color:#0c0e13;border-radius:24px;padding:12px 18px;
  font-size:15px;font-weight:600;box-shadow:0 6px 20px rgba(0,0,0,.45);display:none}
#wfab:active{filter:brightness(.9)}
main{padding:10px 10px calc(env(safe-area-inset-bottom) + 90px)}
#status{padding:6px 4px;font-size:13px;color:var(--muted);min-height:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:8px}
@media(min-width:700px){.grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}}
.tile{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;position:relative}
.tile .imgbox{aspect-ratio:1;display:flex;align-items:center;justify-content:center;
  background:#12151c url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'%3E%3Crect width='10' height='10' fill='%238e9298'/%3E%3Crect x='10' y='10' width='10' height='10' fill='%238e9298'/%3E%3Crect x='10' width='10' height='10' fill='%23ffffff' fill-opacity='.85'/%3E%3Crect y='10' width='10' height='10' fill='%23ffffff' fill-opacity='.85'/%3E%3C/svg%3E")}
.tile img{width:100%;height:100%;object-fit:contain;display:block}
.tile .nm{padding:6px 8px 7px;font-size:12px;line-height:1.3;color:var(--text);
  word-break:break-all;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.tile .sz{font-size:11px;color:var(--muted);display:block;margin-top:2px}
.tile .menu{position:absolute;top:4px;right:4px;background:rgba(23,26,33,.85);
  border:1px solid var(--line);border-radius:8px;padding:2px 8px;font-size:15px;line-height:1.6}
.tile .menu:active{background:#28324a}
.tile.fold{display:flex;align-items:center;gap:10px;padding:12px;font-size:14.5px}
.tile.fold .fi{font-size:22px}
.tile.fold .nm{-webkit-line-clamp:1;flex:1}
.folders{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
.empty{color:var(--muted);text-align:center;padding:36px 12px;font-size:14px}
#toasts{position:fixed;left:50%;transform:translateX(-50%);
  bottom:calc(env(safe-area-inset-bottom) + 16px);z-index:60;display:flex;
  flex-direction:column;gap:8px;width:min(92vw,420px)}
.toast{background:#253048;border:1px solid var(--line);border-radius:11px;
  padding:10px 14px;font-size:14px;box-shadow:0 8px 28px rgba(0,0,0,.5);
  animation:pop .18s ease-out}
.toast.err{border-color:var(--danger)}
.toast.ok{border-color:var(--ok)}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1}}
#viewer{position:fixed;inset:0;z-index:40;background:#0c0e13;display:none;
  flex-direction:column}
#viewer.on{display:flex}
#vimgbox{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}
#vimg{max-width:100%;max-height:100%;object-fit:contain}
#vbar{display:flex;gap:6px;justify-content:center;flex-wrap:wrap;
  padding:10px 8px calc(env(safe-area-inset-bottom) + 10px);background:rgba(23,26,33,.97);
  border-top:1px solid var(--line)}
#vbar .hbtn{font-size:13.5px}
#vname{position:absolute;top:calc(env(safe-area-inset-top) + 8px);left:50%;
  transform:translateX(-50%);max-width:80%;background:rgba(23,26,33,.8);
  border:1px solid var(--line);border-radius:9px;padding:5px 12px;font-size:12.5px;
  color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#vnav{position:absolute;inset:0;display:flex;justify-content:space-between;
  align-items:center;pointer-events:none}
#vnav button{pointer-events:auto;width:44px;height:64px;font-size:26px;color:var(--muted);
  background:rgba(23,26,33,.5);border-radius:10px;margin:0 6px}
#spin{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--muted);font-size:14px}
#sheet{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.45);display:none;
  align-items:flex-end;justify-content:center}
#sheet.on{display:flex}
#sheetbox{background:var(--bg2);border-radius:16px 16px 0 0;width:min(100vw,480px);
  padding:10px 12px calc(env(safe-area-inset-bottom) + 14px);
  border-top:1px solid var(--line);display:flex;flex-direction:column;gap:4px}
#sheetbox .st{font-size:13px;color:var(--muted);padding:4px 8px 8px;word-break:break-all}
#sheetbox button{display:flex;gap:10px;align-items:center;padding:12px 10px;
  border-radius:10px;font-size:15px;text-align:left}
#sheetbox button:active{background:#28324a}
#sheetbox button.dgr{color:#ff8a8a}
#logbox{position:fixed;left:0;right:0;bottom:0;top:20vh;z-index:45;background:#10131a;
  border-top:1px solid var(--line);display:none;flex-direction:column;transform:translateY(0)}
#logbox.on{display:flex}
#logpre{flex:1;overflow:auto;padding:10px 12px;font:12px/1.5 ui-monospace,Consolas,monospace;
  color:#b6c2d4;white-space:pre-wrap;word-break:break-all}
#loghead{display:flex;justify-content:space-between;align-items:center;
  padding:8px 12px;border-bottom:1px solid var(--line);font-size:14px}
dialog.token{background:var(--bg2);color:var(--text);border:1px solid var(--line);
  border-radius:14px;padding:18px;max-width:92vw}
dialog.token::backdrop{background:rgba(0,0,0,.6)}
#needtoken{position:fixed;inset:0;z-index:70;background:var(--bg);display:none;
  align-items:center;justify-content:center;text-align:center;padding:24px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="hrow">
    <button class="hbtn" id="bdrives" title="Диски">💾</button>
    <h1 id="title">Image Hunter</h1>
    <button class="hbtn" id="bweb" title="Интернет">🔎</button>
    <button class="hbtn" id="blog" title="Журнал">📜</button>
    <button class="hbtn" id="blang">EN</button>
  </div>
  <div id="crumbs"></div>
  <div class="srow">
    <select class="sel" id="weng" style="display:none" title="Поисковик">
      <option value="ddg">DuckDuckGo</option>
      <option value="bing">Bing</option>
    </select>
    <input id="q" type="search" placeholder="Поиск по имени…">
    <label class="chk" id="deepwrap"><input type="checkbox" id="deep"><span data-t="deep">вглубь</span></label>
  </div>
</header>
<main>
  <div id="status"></div>
  <div class="folders" id="folders"></div>
  <div class="grid" id="grid"></div>
  <div class="empty" id="empty" style="display:none"></div>
</main>

<div id="viewer">
  <div id="vimgbox">
    <div id="vname"></div>
    <div id="spin"></div>
    <img id="vimg" alt="">
    <div id="vnav">
      <button id="vprev">‹</button>
      <button id="vnext">›</button>
    </div>
  </div>
  <div id="vbar">
    <button class="hbtn" id="vclose" data-t="back">← Назад</button>
    <button class="hbtn" id="vdl" data-t="dl">⬇️ Скачать</button>
    <button class="hbtn" id="vsave" data-t="to_folder_short" style="display:none">💾</button>
    <button class="hbtn" id="vren" data-t="ren">✏️</button>
    <button class="hbtn" id="vnobg" data-t="nobg">🪄</button>
    <button class="hbtn" id="vdel" data-t="del">🗑</button>
  </div>
</div>

<div id="sheet"><div id="sheetbox"></div></div>

<div id="logbox">
  <div id="loghead"><span data-t="log">Журнал</span>
    <button class="hbtn" id="logclose">✕</button></div>
  <div id="logpre"></div>
</div>

<button id="wfab">⬇ <span id="wfabn">0</span></button>
<div id="toasts"></div>
<div id="needtoken"><div><h2 style="color:var(--text)">Image Hunter</h2>
  <p data-t="needtoken" style="margin-top:8px">Откройте ссылку с токеном — адрес есть в программе: кнопка 🌐 в статус-баре.</p>
  <p style="margin-top:12px"><input id="tin" placeholder="token" style="background:var(--bg2);border:1px solid var(--line);border-radius:10px;color:var(--text);padding:9px 12px;outline:none">
  <button class="hbtn" id="tok" data-t="enter">Войти</button></p></div>
</div>

<script>
"use strict";
/* ---------- i18n ---------- */
var T = {
ru:{deep:"вглубь",back:"← Назад",dl:"⬇️ Скачать",ren:"✏️",nobg:"🪄",del:"🗑",
 log:"Журнал",enter:"Войти",needtoken:"Откройте ссылку с токеном — адрес есть в программе: кнопка 🌐 в статус-баре.",
 search_ph:"Поиск по имени…",empty:"Папка пуста — картинок нет",
 empty_q:"Ничего не найдено",loading:"Читаю папку…",searching:"Ищу…",
 drives:"Диски и папки",favorites:"Избранное",up:"Наверх",
 open:"Открыть",download:"Скачать на устройство",rename:"Переименовать",
 removebg:"Удалить фон (rembg)",delq:"Удалить в корзину?",delforever:"Удалить окончательно (мимо корзины)?",
 rename_t:"Новое имя (без расширения можно не менять):",
 deleting:"Удаляю…",deleted:"Удалено: {n}",renamed:"Переименовано",nobg_started:"Удаление фона запущено: {n} файл(ов)",
 nobg_progress:"Удаление фона: {done}/{total} — {name}",nobg_done:"Удаление фона готово (ok: {ok}, ошибок: {fail})",
 nobg_fail:"Не удалось запустить: {err}",err:"Ошибка: {err}",list_err:"Не удалось открыть папку",
 viewonly:"Сервер в режиме «только просмотр» — действия недоступны",
 langs:"EN",log_empty:"Журнал пуст",thumb_err:"Нет превью",
 web_mode:"Интернет",web_search_ph:"Поиск картинок в интернете…",
 web_hint:"Введите запрос — найденные картинки можно скачать в папку на компьютере или на устройство",
 web_no_results:"В интернете ничего не нашлось",web_err:"Поиск не удался: {err}",
 found_n:"Найдено: {n}",more:"Ещё",no_more:"Больше ничего нет",
 to_folder:"💾 В папку на компьютере",to_folder_short:"💾 В папку",
 mark:"Отметить",unmark:"Снять отметку",save_to:"Скачать в папку «{name}»",
 open_folder_first:"Сначала откройте папку в режиме «Файлы» — картинки сохранятся туда",
 dl_started:"Скачивание запущено: {n}",dl_progress:"Скачивание: {done}/{total} — {name}",
 dl_done:"Скачивание готово (скачано: {ok}, ошибок: {fail})"},
en:{deep:"deep",back:"← Back",dl:"⬇️ Save",ren:"✏️",nobg:"🪄",del:"🗑",
 log:"Log",enter:"Enter",needtoken:"Open the link with the token — the address is in the app: the 🌐 button in the status bar.",
 search_ph:"Search by name…",empty:"Folder is empty — no images",
 empty_q:"Nothing found",loading:"Reading folder…",searching:"Searching…",
 drives:"Drives & folders",favorites:"Favorites",up:"Up",
 open:"Open",download:"Save to device",rename:"Rename",
 removebg:"Remove background (rembg)",delq:"Move to recycle bin?",delforever:"Delete permanently (no bin)?",
 rename_t:"New name:",deleting:"Deleting…",deleted:"Deleted: {n}",renamed:"Renamed",
 nobg_started:"Background removal started: {n} file(s)",
 nobg_progress:"Background removal: {done}/{total} — {name}",
 nobg_done:"Background removal finished (ok: {ok}, failed: {fail})",
 nobg_fail:"Could not start: {err}",err:"Error: {err}",list_err:"Could not open folder",
 viewonly:"Server is view-only — actions are disabled",
 langs:"RU",log_empty:"Log is empty",thumb_err:"No preview",
 web_mode:"Web",web_search_ph:"Search images on the web…",
 web_hint:"Type a query — found images can be saved to a computer folder or to this device",
 web_no_results:"Nothing found on the web",web_err:"Search failed: {err}",
 found_n:"Found: {n}",more:"More",no_more:"No more results",
 to_folder:"💾 To a folder on the computer",to_folder_short:"💾 To folder",
 mark:"Mark",unmark:"Unmark",save_to:"Download to folder “{name}”",
 open_folder_first:"Open a folder in Files mode first — images will be saved there",
 dl_started:"Download started: {n}",dl_progress:"Downloading: {done}/{total} — {name}",
 dl_done:"Download finished (saved: {ok}, failed: {fail})"}
};
var lang = (localStorage.getItem("ih_web_lang") ||
            (navigator.language||"").slice(0,2).toLowerCase() === "ru" ? "ru" : "en");
if(!T[lang]) lang = "en";
function t(k, p){ var s = (T[lang][k] || k); if(p) for(var key in p) s = s.split("{"+key+"}").join(p[key]); return s; }
function applyLang(){
  document.documentElement.lang = lang;
  document.getElementById("blang").textContent = T[lang].langs;
  document.getElementById("q").placeholder = t(mode === "web" ? "web_search_ph" : "search_ph");
  document.querySelectorAll("[data-t]").forEach(function(el){ el.textContent = t(el.dataset.t); });
  document.getElementById("empty").textContent =
    mode === "web" ? (wQuery ? t("web_no_results") : t("web_hint"))
                   : (curQ ? t("empty_q") : t("empty"));
}

/* ---------- токен и http ---------- */
var params = new URLSearchParams(location.search);
var TOKEN = params.get("token") || localStorage.getItem("ih_web_token") || "";
if(params.get("token")) localStorage.setItem("ih_web_token", TOKEN);
function api(path, opts){
  var sep = path.indexOf("?") >= 0 ? "&" : "?";
  return fetch(path + sep + "token=" + encodeURIComponent(TOKEN), opts);
}
function apiUrl(path, more){
  var sep = path.indexOf("?") >= 0 ? "&" : "?";
  return path + sep + "token=" + encodeURIComponent(TOKEN) + (more||"");
}
function fmtSize(n){
  if(n > 1048576) return (n/1048576).toFixed(1) + " МБ";
  if(n > 1024) return Math.round(n/1024) + " КБ";
  return n + " Б";
}
function toast(msg, kind){
  var box = document.getElementById("toasts");
  var el = document.createElement("div");
  el.className = "toast" + (kind ? " " + kind : "");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(function(){ el.remove(); }, kind === "err" ? 6000 : 3500);
}
var VIEW_ONLY = false;

/* ---------- состояние ---------- */
var curPath = "", curQ = "", curDeep = false;
var files = [];            // картинки текущей папки/поиска
var listSeq = 0;

/* ---------- режимы: «Файлы» и «Интернет» (кнопка 🔎) ---------- */
var mode = localStorage.getItem("ih_web_mode") === "web" ? "web" : "files";
var wResults = [];         // результаты интернет-поиска
var wQuery = "";
var wsel = {};             // отмеченные плитки выдачи: url -> результат
var webSeq = 0;
var webView = false;       // открыт просмотр результата из интернета
var lastFolder = localStorage.getItem("ih_web_folder") || "";  // куда «В папку»

/* ---------- crumbs ---------- */
function crumbs(path){
  var box = document.getElementById("crumbs");
  box.innerHTML = "";
  var parts = path.split(/[\\/]/).filter(Boolean);
  var acc = parts.length && path[0] !== "/" && path[1] !== ":" ? "" : (path[0] === "/" ? "/" : "");
  function add(label, p, here){
    var a = document.createElement(here ? "span" : "a");
    if(here){ a.className = "here"; } else { a.href = "#"; a.onclick = function(ev){ ev.preventDefault(); openFolder(p); }; }
    a.textContent = label;
    box.appendChild(a);
    var s = document.createElement("span"); s.className = "sep"; s.textContent = "›";
    box.appendChild(s);
  }
  if(path && /^[a-zA-Z]:/.test(path)) add(path.slice(0,2), path.slice(0,2), false);
  else if(path && path[0] === "/") add("/", "/", false);
  parts.forEach(function(p, i){
    var full;
    if(/^[a-zA-Z]:$/.test(p)) full = p + "\\";
    else if(path[0] === "/") full = "/" + parts.slice(0, i+1).join("/");
    else full = (path.slice(0,2) + "\\") + parts.slice(1, i+1).join("\\");
    if(i === 0 && /^[a-zA-Z]:$/.test(p)) return;   // уже нарисовали диск
    add(p, full, i === parts.length - 1);
  });
  box.scrollLeft = box.scrollWidth;
}
function crumbsWeb(){
  var box = document.getElementById("crumbs");
  box.innerHTML = "";
  var s = document.createElement("span"); s.className = "here";
  s.textContent = "🔎 " + (wQuery || t("web_mode"));
  box.appendChild(s);
}

/* ---------- лента ---------- */
function setStatus(s){ document.getElementById("status").textContent = s || ""; }
function openFolder(path){
  curQ = ""; document.getElementById("q").value = "";
  loadFolder(path);
}
function loadFolder(path){
  var seq = ++listSeq;
  curPath = path;
  crumbs(path);
  setStatus(t("loading"));
  document.getElementById("empty").style.display = "none";
  api("/api/list?path=" + encodeURIComponent(path))
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
    .then(function(res){
      if(seq !== listSeq) return;
      if(!res.ok){ setStatus(""); toast(t("list_err") + ": " + (res.j.error||""), "err"); return; }
      render(res.j);
      setStatus("");
    })
    .catch(function(e){ if(seq === listSeq){ setStatus(""); toast(t("err", {err: e}), "err"); } });
}
function render(j){
  curPath = j.path;
  lastFolder = j.path;
  try{ localStorage.setItem("ih_web_folder", j.path); }catch(e){}
  if(mode === "web") return;   // телефон в интернете: папка грузится лишь для «В папку»
  files = j.files;
  var fbox = document.getElementById("folders");
  var grid = document.getElementById("grid");
  fbox.innerHTML = ""; grid.innerHTML = "";
  if(j.parent && j.parent !== j.path){
    var up = document.createElement("button");
    up.className = "tile fold";
    up.innerHTML = "<span class='fi'>↩️</span><span class='nm'>" + esc(t("up")) + " — " + esc(baseName(j.parent)) + "</span>";
    up.onclick = function(){ openFolder(j.parent); };
    fbox.appendChild(up);
  }
  j.folders.forEach(function(f){
    var el = document.createElement("button");
    el.className = "tile fold";
    el.innerHTML = "<span class='fi'>📁</span><span class='nm'>" + esc(f.name) + "</span>";
    el.onclick = function(){ openFolder(f.path); };
    fbox.appendChild(el);
  });
  files.forEach(function(f, i){ grid.appendChild(tile(f, i)); });
  var empty = document.getElementById("empty");
  var any = j.folders.length || files.length;
  empty.style.display = any ? "none" : "block";
  empty.textContent = curQ ? t("empty_q") : t("empty");
  document.title = "Image Hunter — " + baseName(j.path);
}
function tile(f, i){
  var el = document.createElement("div");
  el.className = "tile";
  var box = document.createElement("div"); box.className = "imgbox";
  var img = document.createElement("img");
  img.loading = "lazy"; img.decoding = "async";
  img.src = apiUrl("/api/thumb", "&path=" + encodeURIComponent(f.path) + "&size=320");
  img.onerror = function(){ img.replaceWith(Object.assign(document.createElement("div"),
      {textContent: "🖼", style: "font-size:26px;opacity:.5"})); };
  box.appendChild(img);
  var nm = document.createElement("div"); nm.className = "nm";
  nm.innerHTML = esc(f.name) + "<span class='sz'>" + fmtSize(f.size) + "</span>";
  var mb = document.createElement("button"); mb.className = "menu"; mb.textContent = "⋮";
  mb.onclick = function(ev){ ev.stopPropagation(); sheet(f, i); };
  el.appendChild(box); el.appendChild(nm); el.appendChild(mb);
  el.onclick = function(){ openViewer(i); };
  return el;
}
function esc(s){ return String(s).replace(/[&<>"']/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]; }); }
function baseName(p){ return p.split(/[\\/]/).filter(Boolean).pop() || p; }

/* ---------- поиск ---------- */
var qTimer = null;
document.getElementById("q").addEventListener("input", function(){
  clearTimeout(qTimer);
  qTimer = setTimeout(mode === "web" ? webSearch : runSearch, mode === "web" ? 600 : 350);
});
document.getElementById("q").addEventListener("keydown", function(ev){
  if(ev.key === "Enter"){ ev.preventDefault(); clearTimeout(qTimer);
    if(mode === "web") webSearch(); else runSearch(); }
});
document.getElementById("weng").addEventListener("change", function(){
  if(mode === "web" && wQuery) webSearch();
});
document.getElementById("deep").addEventListener("change", function(){
  if(mode === "files" && document.getElementById("q").value.trim()) runSearch();
});
function runSearch(){
  var q = document.getElementById("q").value.trim();
  var deep = document.getElementById("deep").checked;
  if(!q){ loadFolder(curPath); return; }
  var seq = ++listSeq;
  curQ = q;
  setStatus(t("searching"));
  document.getElementById("empty").style.display = "none";
  api("/api/search?path=" + encodeURIComponent(curPath) + "&q=" + encodeURIComponent(q)
      + (deep ? "&deep=1" : "") + "&dash=1")
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
    .then(function(res){
      if(seq !== listSeq) return;
      if(!res.ok){ setStatus(""); toast(t("err", {err: res.j.error||""}), "err"); return; }
      files = res.j.files;
      var fbox = document.getElementById("folders"); fbox.innerHTML = "";
      var grid = document.getElementById("grid"); grid.innerHTML = "";
      files.forEach(function(f, i){ grid.appendChild(tile(f, i)); });
      crumbs(curPath);
      setStatus(res.j.truncated ? ("2000+") : "");
      var empty = document.getElementById("empty");
      empty.style.display = files.length ? "none" : "block";
      empty.textContent = t("empty_q");
    });
}

/* ---------- интернет-поиск ---------- */
function setMode(m, skipLoad){
  mode = m;
  try{ localStorage.setItem("ih_web_mode", m); }catch(e){}
  document.getElementById("bweb").classList.toggle("on", m === "web");
  document.getElementById("weng").style.display = m === "web" ? "" : "none";
  document.getElementById("deepwrap").style.display = m === "web" ? "none" : "";
  document.getElementById("bdrives").style.display = m === "web" ? "none" : "";
  document.getElementById("folders").style.display = m === "web" ? "none" : "";
  document.getElementById("q").placeholder = t(m === "web" ? "web_search_ph" : "search_ph");
  document.getElementById("q").value = m === "web" ? wQuery : "";
  if(m === "web"){
    files = [];                       // плитки файлов больше не видны
    if(wQuery) webSearch();
    else { renderWeb(); setStatus(""); }
  } else {
    wsel = {};
    updWfab();
    crumbs(curPath);
    if(!skipLoad){ if(curQ) runSearch(); else loadFolder(curPath || ""); }
  }
}
document.getElementById("bweb").onclick = function(){
  setMode(mode === "web" ? "files" : "web");
};
function webSearch(){
  var q = document.getElementById("q").value.trim();
  wQuery = q;
  if(!q){ wResults = []; renderWeb(); return; }
  var seq = ++webSeq;
  setStatus(t("searching"));
  document.getElementById("empty").style.display = "none";
  api("/api/web/search?engine=" + encodeURIComponent(document.getElementById("weng").value)
      + "&q=" + encodeURIComponent(q))
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, code: r.status, j: j}; }); })
    .then(function(res){
      if(seq !== webSeq) return;
      if(!res.ok){ wResults = []; renderWeb(); setStatus("");
                   toast(t("web_err", {err: res.j.error || res.code}), "err"); return; }
      wResults = res.j.results || [];
      renderWeb();
      setStatus(t("found_n", {n: wResults.length}));
    })
    .catch(function(e){ if(seq === webSeq){ setStatus(""); toast(t("err", {err: e}), "err"); } });
}
function webMore(){
  if(!wQuery) return;
  var seq = ++webSeq;
  setStatus(t("searching"));
  api("/api/web/search?engine=" + encodeURIComponent(document.getElementById("weng").value)
      + "&q=" + encodeURIComponent(wQuery) + "&offset=" + wResults.length)
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, code: r.status, j: j}; }); })
    .then(function(res){
      if(seq !== webSeq) return;
      setStatus("");
      if(!res.ok){ toast(t("web_err", {err: res.j.error || res.code}), "err"); return; }
      var add = (res.j.results || []).filter(function(x){
        return !wResults.some(function(y){ return y.url === x.url; });
      });
      if(!add.length){ toast(t("no_more")); return; }
      wResults = wResults.concat(add);
      renderWeb();
      setStatus(t("found_n", {n: wResults.length}));
    })
    .catch(function(e){ setStatus(""); toast(t("err", {err: e}), "err"); });
}
function renderWeb(){
  var fbox = document.getElementById("folders"); fbox.innerHTML = "";
  var grid = document.getElementById("grid"); grid.innerHTML = "";
  wResults.forEach(function(f, i){ grid.appendChild(wtile(f, i)); });
  if(wResults.length && wQuery){
    var more = document.createElement("button");
    more.className = "tile fold";
    more.innerHTML = "<span class='fi'>⏬</span><span class='nm'>" + esc(t("more")) + "</span>";
    more.onclick = webMore;
    grid.appendChild(more);
  }
  crumbsWeb();
  var empty = document.getElementById("empty");
  empty.style.display = wResults.length ? "none" : "block";
  empty.textContent = wQuery ? t("web_no_results") : t("web_hint");
  document.title = "Image Hunter — 🔎 " + (wQuery || t("web_mode"));
  updWfab();
}
function baseNameUrl(u){
  var b = String(u).split("?")[0].split("/").pop() || u;
  try{ return decodeURIComponent(b); }catch(e){ return b; }
}
function wtile(f, i){
  var el = document.createElement("div");
  el.className = "tile";
  var box = document.createElement("div"); box.className = "imgbox";
  var img = document.createElement("img");
  img.loading = "lazy"; img.decoding = "async";
  img.src = f.thumb || f.url;
  img.onerror = function(){
    if(img.dataset.px){ img.replaceWith(Object.assign(document.createElement("div"),
        {textContent: "🖼", style: "font-size:26px;opacity:.5"})); return; }
    img.dataset.px = "1";   // CDN не отдал превью — попробуем через сервер
    img.src = apiUrl("/api/web/proxy", "&url=" + encodeURIComponent(f.thumb || f.url));
  };
  box.appendChild(img);
  var nm = document.createElement("div"); nm.className = "nm";
  var dim = (f.w && f.h) ? (f.w + "×" + f.h) : "";
  nm.innerHTML = esc(f.title || baseNameUrl(f.url))
               + (dim ? "<span class='sz'>" + dim + "</span>" : "");
  var cb = document.createElement("button");
  cb.className = "ckb" + (wsel[f.url] ? " on" : "");
  cb.textContent = wsel[f.url] ? "✓" : "+";
  cb.onclick = function(ev){ ev.stopPropagation(); toggleSel(f);
    cb.className = "ckb" + (wsel[f.url] ? " on" : "");
    cb.textContent = wsel[f.url] ? "✓" : "+"; };
  var mb = document.createElement("button"); mb.className = "menu"; mb.textContent = "⋮";
  mb.onclick = function(ev){ ev.stopPropagation(); wsheet(f, i); };
  el.appendChild(box); el.appendChild(nm); el.appendChild(cb); el.appendChild(mb);
  el.onclick = function(){ openWebViewer(i); };
  return el;
}
function wsheet(f, i){
  sheetItem = {f: f, i: i, web: true};
  var box = document.getElementById("sheetbox");
  box.innerHTML = "<div class='st'>" + esc(f.title || baseNameUrl(f.url))
                + "</div><div class='st' style='opacity:.7'>" + esc(f.url) + "</div>";
  addAct(box, "↗️ " + t("open"), function(){ closeSheet(); openWebViewer(i); });
  addAct(box, "⬇️ " + t("download"), function(){ closeSheet();
      location.href = apiUrl("/api/web/proxy", "&dl=1&url=" + encodeURIComponent(f.url)); });
  if(!VIEW_ONLY) addAct(box, "💾 " + t("to_folder"), function(){ closeSheet(); webDownload([f.url]); });
  addAct(box, (wsel[f.url] ? "✕ " : "✓ ") + (wsel[f.url] ? t("unmark") : t("mark")),
         function(){ closeSheet(); toggleSel(f); renderWeb(); });
  var cancel = document.createElement("button");
  cancel.textContent = "✕"; cancel.onclick = closeSheet;
  box.appendChild(cancel);
  document.getElementById("sheet").classList.add("on");
}
function toggleSel(f){
  if(wsel[f.url]) delete wsel[f.url]; else wsel[f.url] = f;
  updWfab();
}
function updWfab(){
  var n = Object.keys(wsel).length;
  document.getElementById("wfabn").textContent = n;
  var show = mode === "web" && n > 0 && !VIEW_ONLY && !!lastFolder;
  document.getElementById("wfab").style.display = show ? "block" : "none";
  document.getElementById("wfab").title = t("save_to", {name: baseName(lastFolder) || lastFolder});
}
document.getElementById("wfab").onclick = function(){
  var urls = Object.keys(wsel);
  if(urls.length) webDownload(urls);
};
function webDownload(urls){
  if(VIEW_ONLY){ toast(t("viewonly"), "err"); return; }
  if(!lastFolder){ toast(t("open_folder_first"), "err"); return; }
  api("/api/web/download", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({urls: urls, folder: lastFolder})})
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, code: r.status, j: j}; }); })
    .then(function(res){
      if(res.ok || res.code === 202){
        toast(t("dl_started", {n: res.j.total}) + " → " + (baseName(lastFolder) || lastFolder), "ok");
        pollJob(res.j.id);
      } else toast(t("nobg_fail", {err: res.j.error || res.code}), "err");
    });
}
function openWebViewer(i){
  vIndex = i;
  var f = wResults[i];
  if(!f) return;
  webView = true;
  setWebBar(true);
  document.getElementById("viewer").classList.add("on");
  document.getElementById("vname").textContent = f.title || baseNameUrl(f.url);
  var img = document.getElementById("vimg");
  document.getElementById("spin").textContent = "…";
  img.style.display = "none";
  img.onload = function(){ img.style.display = "block";
                           document.getElementById("spin").textContent = ""; };
  img.onerror = function(){ document.getElementById("spin").textContent = t("thumb_err"); };
  // оригинал — через сервер: сайты с проверкой Referer не отдают картинку
  // странице телефона напрямую
  img.src = apiUrl("/api/web/proxy", "&url=" + encodeURIComponent(f.url));
  document.getElementById("vnav").style.display = wResults.length > 1 ? "flex" : "none";
}
function setWebBar(web){
  document.getElementById("vsave").style.display = (web && !VIEW_ONLY) ? "" : "none";
  document.getElementById("vren").style.display = web ? "none" : "";
  document.getElementById("vnobg").style.display = web ? "none" : "";
  document.getElementById("vdel").style.display = web ? "none" : "";
}
document.getElementById("vsave").onclick = function(){
  if(mode === "web" && !VIEW_ONLY){
    var f = wResults[vIndex];
    if(f) webDownload([f.url]);
  }
};

/* ---------- меню действий ---------- */
var sheetItem = null;
function sheet(f, i){
  sheetItem = {f: f, i: i};
  var box = document.getElementById("sheetbox");
  box.innerHTML = "<div class='st'>" + esc(f.path) + "</div>";
  addAct(box, "↗️ " + t("open"), function(){ closeSheet(); openViewer(i); });
  addAct(box, "⬇️ " + t("download"), function(){ closeSheet(); location.href =
      apiUrl("/api/raw", "&path=" + encodeURIComponent(f.path)); });
  if(!VIEW_ONLY){
    addAct(box, "✏️ " + t("rename"), function(){ closeSheet(); doRename(f); });
    addAct(box, "🪄 " + t("removebg"), function(){ closeSheet(); doNobg([f.path]); });
    addAct(box, "🗑 " + t("delq"), function(){ closeSheet(); doDelete(f.path, false); }, true);
  }
  var cancel = document.createElement("button");
  cancel.textContent = "✕"; cancel.onclick = closeSheet;
  box.appendChild(cancel);
  document.getElementById("sheet").classList.add("on");
}
function addAct(box, label, fn, dgr){
  var b = document.createElement("button");
  if(dgr) b.className = "dgr";
  b.textContent = label; b.onclick = fn;
  box.appendChild(b);
}
function closeSheet(){ document.getElementById("sheet").classList.remove("on"); }
document.getElementById("sheet").addEventListener("click", function(ev){
  if(ev.target.id === "sheet") closeSheet();
});

/* ---------- действия ---------- */
function doRename(f){
  var stem = f.name.replace(/\.[^.]+$/, "");
  var ext = f.name.slice(stem.length);
  var name = prompt(t("rename_t"), stem);
  if(name === null) return;
  if(ext) name = name + ext;
  api("/api/rename", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: f.path, name: name})})
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
    .then(function(res){
      if(res.ok){ toast(t("renamed"), "ok"); refresh(); }
      else toast(t("err", {err: res.j.error||""}), "err");
    });
}
function doDelete(path, permanent){
  if(!confirm(permanent ? t("delforever") : t("delq"))) return;
  toast(t("deleting"));
  api("/api/delete", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paths: [path], permanent: permanent})})
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
    .then(function(res){
      if(!res.ok){ toast(t("err", {err: res.j.error||""}), "err"); return; }
      var r0 = res.j.results[0];
      if(r0 && r0.ok) toast(t("deleted", {n: 1}), "ok");
      else toast(t("err", {err: (r0 && r0.error) || ""}), "err");
      refresh();
    });
}
function doNobg(paths){
  api("/api/rembg", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paths: paths})})
    .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j, code: r.status}; }); })
    .then(function(res){
      if(res.ok || res.code === 202){
        toast(t("nobg_started", {n: res.j.total}), "ok");
        pollJob(res.j.id);
      } else toast(t("nobg_fail", {err: res.j.error||res.code}), "err");
    });
}
var jobTimer = null;
function pollJob(id){
  clearTimeout(jobTimer);
  api("/api/job/status?id=" + encodeURIComponent(id))
    .then(function(r){ return r.json(); })
    .then(function(j){
      if(j.state === "running"){
        setStatus(j.kind === "webdl"
          ? t("dl_progress", {done: j.done, total: j.total, name: j.current || ""})
          : t("nobg_progress", {done: j.done, total: j.total, name: j.current || ""}));
        jobTimer = setTimeout(function(){ pollJob(id); }, 1000);
      } else if(j.state === "done"){
        setStatus("");
        if(j.kind === "webdl"){
          toast(t("dl_done", {ok: j.ok, fail: j.fail}), j.fail ? "" : "ok");
          wsel = {};
          updWfab();
          if(mode === "web") renderWeb();
        } else {
          toast(t("nobg_done", {ok: j.ok, fail: j.fail}), j.fail ? "" : "ok");
          refresh();
        }
      } else {
        setStatus("");
        toast(t("nobg_fail", {err: j.error || ""}), "err");
      }
    })
    .catch(function(){});
}
function refresh(){
  if(curQ) runSearch(); else loadFolder(curPath);
}

/* ---------- просмотр ---------- */
var vIndex = -1;
function openViewer(i){
  vIndex = i;
  webView = false;
  setWebBar(false);
  var f = files[i];
  if(!f) return;
  document.getElementById("viewer").classList.add("on");
  document.getElementById("vname").textContent = f.name;
  var img = document.getElementById("vimg");
  document.getElementById("spin").textContent = "…";
  img.style.display = "none";
  img.onload = function(){ img.style.display = "block";
                           document.getElementById("spin").textContent = ""; };
  img.onerror = function(){ document.getElementById("spin").textContent = t("thumb_err"); };
  img.src = apiUrl("/api/image", "&path=" + encodeURIComponent(f.path));
  document.getElementById("vnav").style.display = files.length > 1 ? "flex" : "none";
}
function closeViewer(){ document.getElementById("viewer").classList.remove("on");
                        document.getElementById("vimg").src = "";
                        webView = false; setWebBar(false); }
function vStep(d){
  if(webView){
    if(!wResults.length) return;
    openWebViewer((vIndex + d + wResults.length) % wResults.length);
    return;
  }
  if(!files.length) return;
  openViewer((vIndex + d + files.length) % files.length);
}
document.getElementById("vclose").onclick = closeViewer;
document.getElementById("vprev").onclick = function(ev){ ev.stopPropagation(); vStep(-1); };
document.getElementById("vnext").onclick = function(ev){ ev.stopPropagation(); vStep(1); };
document.getElementById("vdl").onclick = function(){
  var f = files[vIndex]; if(f) location.href = apiUrl("/api/raw", "&path=" + encodeURIComponent(f.path));
};
document.getElementById("vren").onclick = function(){
  var f = files[vIndex]; if(f && !VIEW_ONLY){ closeViewer(); sheet(f, vIndex); }
};
document.getElementById("vnobg").onclick = function(){
  var f = files[vIndex]; if(f && !VIEW_ONLY){ doNobg([f.path]); }
};
document.getElementById("vdel").onclick = function(){
  var f = files[vIndex]; if(f && !VIEW_ONLY){ closeViewer(); doDelete(f.path, false); }
};
(function(){ // свайпы и клавиатура в просмотре
  var x0 = null, y0 = null;
  var box = document.getElementById("vimgbox");
  box.addEventListener("touchstart", function(ev){
    x0 = ev.touches[0].clientX; y0 = ev.touches[0].clientY; }, {passive: true});
  box.addEventListener("touchend", function(ev){
    if(x0 === null) return;
    var dx = ev.changedTouches[0].clientX - x0;
    var dy = ev.changedTouches[0].clientY - y0;
    if(Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) vStep(dx < 0 ? 1 : -1);
    x0 = null; }, {passive: true});
  document.addEventListener("keydown", function(ev){
    if(!document.getElementById("viewer").classList.contains("on")) return;
    if(ev.key === "ArrowLeft") vStep(-1);
    else if(ev.key === "ArrowRight") vStep(1);
    else if(ev.key === "Escape") closeViewer();
  });
})();

/* ---------- диски ---------- */
document.getElementById("bdrives").onclick = function(){
  api("/api/drives").then(function(r){ return r.json(); }).then(function(j){
    var box = document.getElementById("sheetbox");
    box.innerHTML = "<div class='st'>" + esc(t("drives")) + "</div>";
    (j.drives||[]).forEach(function(d){
      var label = (d.kind === "favorite" ? "⭐ " : "") + (d.label || d.path);
      addAct(box, (d.kind === "remote" ? "🌐 " : "") + label,
             function(){ closeSheet(); curQ = ""; document.getElementById("q").value = "";
                         loadFolder(d.path); });
    });
    var cancel = document.createElement("button");
    cancel.textContent = "✕"; cancel.onclick = closeSheet;
    box.appendChild(cancel);
    document.getElementById("sheet").classList.add("on");
  }).catch(function(e){ toast(t("err", {err: e}), "err"); });
};

/* ---------- журнал ---------- */
document.getElementById("blog").onclick = function(){
  api("/api/log?n=200").then(function(r){ return r.json(); }).then(function(j){
    var lines = j.lines || [];
    document.getElementById("logpre").textContent =
      lines.length ? lines.join("\n") : t("log_empty");
    document.getElementById("logbox").classList.add("on");
    var pre = document.getElementById("logpre");
    pre.scrollTop = pre.scrollHeight;
  });
};
document.getElementById("logclose").onclick = function(){
  document.getElementById("logbox").classList.remove("on");
};

/* ---------- язык ---------- */
document.getElementById("blang").onclick = function(){
  lang = lang === "ru" ? "en" : "ru";
  localStorage.setItem("ih_web_lang", lang);
  applyLang();
};

/* ---------- старт ---------- */
if(!TOKEN){
  document.getElementById("needtoken").style.display = "flex";
  document.getElementById("tok").onclick = function(){
    var v = document.getElementById("tin").value.trim();
    if(v){ TOKEN = v; localStorage.setItem("ih_web_token", v);
           document.getElementById("needtoken").style.display = "none";
           boot(); }
  };
}
function boot(){
  api("/api/ping").then(function(r){ return r.json(); }).then(function(j){
    VIEW_ONLY = !!j.view_only;
    document.getElementById("title").textContent = "Image Hunter" +
      (j.version ? " " + j.version : "");
    applyLang();
    // стартовая папка: ?path= из ссылки, иначе первый разрешённый корень
    // (режим ограничения), иначе — первый диск из списка; грузится всегда,
    // даже в режиме «Интернет»: оттуда берётся папка для «💾 В папку»
    var start = params.get("path") || j.root || "";
    if(start) loadFolder(start);
    else api("/api/drives").then(function(r){ return r.json(); }).then(function(j2){
      var d = (j2.drives||[]).find(function(x){ return x.kind === "favorite"; })
              || (j2.drives||[])[0];
      loadFolder(d ? d.path : "");
    }).catch(function(){ loadFolder(""); });
    setMode(mode, true);   // вернуть сохранённый режим; «Файлы» уже грузятся выше
  }).catch(function(){
    localStorage.removeItem("ih_web_token");
    document.getElementById("needtoken").style.display = "flex";
  });
}
if(TOKEN) boot(); else applyLang();
</script>
</body>
</html>
"""

PAGE_401 = r"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image Hunter — нужен токен</title>
<style>body{background:#171a21;color:#9aa5b5;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:24px}
b{color:#e8edf5}</style></head>
<body><div>
<b>Image Hunter</b><br><br>
Нужен токен доступа — откройте ссылку с токеном.<br>
Адрес с токеном есть в программе: кнопка <b>🌐</b> в статус-баре.<br><br>
<span style="font-size:13px">Access token required — open the token link from the app (🌐 button).</span>
</div></body></html>
"""
