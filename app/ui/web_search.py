"""Вкладка «Поиск картинок»: встроенный браузер поисковиков + сбор ссылок.

Три способа отправить картинки дальше:
1. «Собрать ссылки» — все картинки текущей страницы выдачи (превью);
2. «Скачать отмеченные» — только отмеченные галочками плитки, причём
   для каждой берётся большой оригинал (origUrl / img_url), а не превью;
3. «Сохранить в папку» — отмеченные плитки перекодируются в выбранный
   формат (WebP/PNG/JPEG/BMP/TIFF) и сохраняются в папку, открытую
   во вкладке «Мои картинки» (название.ext, название-1.ext…).
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, urlparse

from PySide6.QtCore import QSettings, QTimer, QUrl, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import i18n
from app.core.extractor import (
    collect_image_urls,
    fetch_checked_selections,
    inject_checkbox_ui,
    uncheck_all_selections,
)
from app.core.i18n import tr
from app.core.image_saver import SAVE_FORMATS

# (полное имя в списке, шаблон поиска, короткое имя вкладки, фирменный цвет бренда)
ENGINES: list[tuple[str, str, str, str]] = [
    ("Яндекс.Картинки", "https://ya.ru/images/search?text={}",
     "Яндекс", "#FC3F1D"),
    # iax=images&ia=images — канонический адрес выдачи картинок DDG (устаревший
    # iar=images страницу картинок больше не открывает); kp=1 — строгий safe search
    ("DuckDuckGo (safe)", "https://duckduckgo.com/?q={}&iax=images&ia=images&kp=1&t=h_",
     "DuckDuckGo", "#DE5833"),
    ("Google Картинки", "https://www.google.com/search?q={}&udm=2",
     "Google", "#4285F4"),
    ("Bing Картинки", "https://www.bing.com/images/search?q={}",
     "Bing", "#008373"),
    ("Brave Картинки", "https://search.brave.com/images?q={}",
     "Brave", "#FB542B"),
    ("Startpage Картинки", "https://www.startpage.com/sp/search?query={}&cat=images",
     "Startpage", "#6573FF"),
    ("Mojeek Картинки", "https://www.mojeek.com/images?q={}",
     "Mojeek", "#455A64"),
    ("Baidu Картинки", "https://image.baidu.com/search/index?tn=baiduimage&ie=utf-8&word={}",
     "Baidu", "#2932E1"),
    ("Sogou Картинки", "https://pic.sogou.com/pics?query={}",
     "Sogou", "#FF6A00"),
    ("Naver Картинки", "https://search.naver.com/search.naver?where=image&query={}",
     "Naver", "#03C75A"),
    ("Mail.ru Картинки", "https://go.mail.ru/search_images?q={}",
     "Mail.ru", "#005FF9"),
]

_YANDEX_HOSTS = ("ya.ru", "yandex.ru", "yandex.com", "yandex.by", "yandex.kz", "yandex.uz")


def is_image_search_url(url: str) -> bool:
    """Это страница картинок известного поисковика? (только там ставим чекбоксы)"""
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        path = parts.path or ""
        query = parse_qs(parts.query or "")
    except Exception:
        return False
    have = lambda k: (query.get(k) or [""])[0]  # noqa: E731
    if any(host == h or host.endswith("." + h) for h in _YANDEX_HOSTS):
        return path.startswith("/images")
    if host.endswith("duckduckgo.com"):
        # выдача картинок: iax/ia (актуально) или iar (старые сохранённые ссылки)
        return "images" in (have("ia"), have("iax"), have("iar"))
    if host.endswith(("google.com", "google.ru", "google.by", "google.kz", "google.com.ua")):
        return (query.get("udm") or [""])[0] == "2" or path.startswith("/imgres")
    if host.endswith("bing.com"):
        return path.startswith("/images")
    if host.endswith("brave.com"):
        return path.startswith("/images")
    if host.endswith("mojeek.com"):
        return path.startswith("/images")
    if host == "image.baidu.com":
        return True
    if host == "pic.sogou.com":
        return True
    if host.endswith("naver.com"):
        return have("where") == "image" or path.startswith("/image-search")
    if host.endswith("startpage.com"):
        return path.startswith(("/sp/search", "/do/search")) and have("cat") == "images"
    if host == "go.mail.ru":
        return path.startswith("/search_images")
    return False


class WebSearch(QWidget):
    """Строка поиска + встроенный браузер + чекбоксы на плитках + сбор ссылок.

    У части поисковиков выдача открыта не в главной странице, а во вложенном
    фрейме (Mail.ru показывает Яндекс.Картинки внутри go.mail.ru) — поэтому
    инъекция чекбоксов, опрос отметок и сбор ссылок выполняются во всех
    фреймах-выдачах (см. _serp_frames), а не только на самой странице.
    """

    images_found = Signal(list, str)  # (ссылки, URL страницы-источника)
    checked_count_changed = Signal(int)  # сколько плиток отмечено
    save_requested = Signal(list, str)  # (оригиналы отмеченных, referer)

    def __init__(self, parent=None):
        super().__init__(parent)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)

        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("ws.query_ph"))
        self.query.returnPressed.connect(self.search)

        self.engine = QComboBox()
        self.engine.addItems([name for name, _u, _s, _c in ENGINES])
        self.engine.setToolTip(tr("ws.engine_tip"))

        self.go_btn = QToolButton()
        self.go_btn.setText(tr("ws.find"))
        self.go_btn.clicked.connect(self.search)

        self.collect_btn = QToolButton()
        self.collect_btn.setText(tr("ws.collect"))
        self.collect_btn.setToolTip(tr("ws.collect_tip"))
        self.collect_btn.clicked.connect(self.collect)

        self.btn_checked = QToolButton()
        self.btn_checked.setText(tr("ws.download_checked"))
        self.btn_checked.setToolTip(tr("ws.download_checked_tip"))
        self.btn_checked.setEnabled(False)
        self.btn_checked.clicked.connect(self.download_checked)

        # формат сохранения отмеченных картинок (выбор запоминается)
        self.format_box = QComboBox()
        self.format_box.addItems(list(SAVE_FORMATS))
        self.format_box.setToolTip(tr("ws.format_tip"))
        saved_fmt = QSettings("ImageHunter", "ImageHunter").value(
            "web/save_format", "", str) or ""
        if saved_fmt in SAVE_FORMATS:
            self.format_box.setCurrentText(saved_fmt)
        self.format_box.currentTextChanged.connect(self._on_format_changed)

        self.btn_save = QToolButton()
        self.btn_save.setText(tr("ws.save"))
        self.btn_save.setToolTip(tr("ws.save_tip", ext=self.current_ext()))
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_checked)

        self.btn_clear = QToolButton()
        self.btn_clear.setText(tr("ws.clear"))
        self.btn_clear.setToolTip(tr("ws.clear_tip"))
        self.btn_clear.setEnabled(False)
        self.btn_clear.clicked.connect(self.clear_checked)

        bar.addWidget(self.query, 1)
        bar.addWidget(self.engine)
        bar.addWidget(self.go_btn)
        bar.addWidget(self.collect_btn)
        bar.addWidget(self.btn_checked)
        bar.addWidget(self.format_box)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_clear)

        self.view = QWebEngineView()
        self.view.setUrl(QUrl("https://ya.ru/images/"))
        self.view.loadFinished.connect(self._on_load_finished)
        # SPA-переходы (новый поиск изнутри страницы Google/DDG) меняют URL
        # без перезагрузки — инъекция идемпотентна, ставим чекбоксы и на неё
        self.view.urlChanged.connect(self._on_url_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)

        # счётчик отмеченных плиток — лёгкий опрос страницы
        self._checked_count = 0
        self._poll = QTimer(self)
        self._poll.setInterval(700)
        self._poll.timeout.connect(self._poll_checked_count)
        self._poll.start()
        i18n.signals.changed.connect(self._retranslate)

    # ---------- действия ----------

    def current_format(self) -> str:
        """Выбранный формат сохранения (ключ в image_saver.SAVE_FORMATS)."""
        return self.format_box.currentText()

    def engine_meta(self) -> tuple[str, str, str, str]:
        """Метаданные выбранного поисковика: (имя, шаблон, коротко, цвет)."""
        return ENGINES[self.engine.currentIndex()]

    def current_ext(self) -> str:
        """Расширение выбранного формата: «.webp», «.png»…"""
        return SAVE_FORMATS[self.current_format()][1]

    def _on_format_changed(self, fmt: str) -> None:
        QSettings("ImageHunter", "ImageHunter").setValue("web/save_format", fmt)
        self.btn_save.setToolTip(tr("ws.save_tip", ext=self.current_ext()))

    def search(self) -> None:
        text = self.query.text().strip()
        if not text:
            self.query.setFocus()
            return
        template = self.engine_meta()[1]
        self.view.load(QUrl(template.format(quote_plus(text))))

    def collect(self) -> None:
        def emit(parts: list) -> None:
            seen: set[str] = set()
            urls: list[str] = []
            for part in parts:
                for u in part:
                    if u not in seen:
                        seen.add(u)
                        urls.append(u)
            self._on_collected(urls)

        self._gather_serp(collect_image_urls, emit)

    def download_checked(self) -> None:
        """Отправить в загрузки оригиналы отмеченных галочками плиток."""
        def emit(parts: list) -> None:
            seen: set[str] = set()
            items: list[dict] = []
            for part in parts:
                for it in part:
                    key = it.get("best")
                    if key and key not in seen:
                        seen.add(key)
                        items.append(it)
            self._on_checked(items)

        self._gather_serp(fetch_checked_selections, emit)

    def save_checked(self) -> None:
        """Отмеченные плитки → перекодировать в выбранный формат → папка из «Моих картинок»."""
        def emit(parts: list) -> None:
            seen: set[str] = set()
            items: list[dict] = []
            for part in parts:
                for it in part:
                    key = it.get("best")
                    if key and key not in seen:
                        seen.add(key)
                        items.append(it)
            self._on_checked_save(items)

        self._gather_serp(fetch_checked_selections, emit)

    def clear_checked(self) -> None:
        """Снять все отметки с плиток на текущей странице выдачи."""
        for target in (self._serp_frames() or [self._main_frame()]):
            uncheck_all_selections(target)
        # мгновенный отклик кнопок, не дожидаясь следующего опроса (700 мс)
        self._on_poll_result(0)

    # ---------- внутреннее ----------

    def _on_collected(self, urls: list[str]) -> None:
        if not urls:
            self._info_no_links()
            return
        self.images_found.emit(urls, self.view.url().toString())

    def _on_checked(self, items: list[dict]) -> None:
        best = [it["best"] for it in items if it.get("best")]
        if not best:
            self._info_no_checked()
            return
        self.images_found.emit(best, self.view.url().toString())

    def _on_checked_save(self, items: list[dict]) -> None:
        best = [it["best"] for it in items if it.get("best")]
        if not best:
            self._info_no_checked()
            return
        self.save_requested.emit(best, self.view.url().toString())

    def _info_no_checked(self) -> None:
        QMessageBox.information(self, "Image Hunter", tr("ws.no_checked"))

    def _info_no_links(self) -> None:
        QMessageBox.information(self, "Image Hunter", tr("ws.no_links"))

    # ---------- фреймы выдачи (Mail.ru показывает Яндекс во вложенном фрейме) ----------

    def _main_frame(self):
        """Главный фрейм встроенного браузера (QWebEngineFrame)."""
        return self.view.page().mainFrame()

    def _serp_frames(self) -> list:
        """Все фреймы, где сейчас открыта выдача картинок.

        У большинства поисковиков это главный фрейм; у Mail.ru — вложенный
        фрейм yandex.ru/images/search внутри go.mail.ru. Обходим дерево
        фреймов (mainFrame().children()) и отбираем те, чей URL — страница
        картинок известного поисковика.
        """
        out = []
        try:
            stack = [self._main_frame()]
        except Exception:
            return out
        seen = 0
        while stack and seen < 16:   # параноидальный предел числа фреймов
            fr = stack.pop()
            seen += 1
            try:
                stack.extend(fr.children())
                if not fr.isValid():
                    continue
                url = fr.url().toString()
            except Exception:
                continue
            if is_image_search_url(url):
                out.append(fr)
        return out

    def _gather_serp(self, run_one, emit, timeout_ms: int = 4000) -> None:
        """Выполнить ``run_one(target, callback)`` на каждом фрейме выдачи.

        ``emit(parts)`` получает список результатов, когда все фреймы
        ответили (или по таймауту — фрейм мог исчезнуть и не ответить).
        Если выдачи нигде нет, сбор идёт на главном фрейме — как раньше.

        Колбэки хранятся в списке всё время ожидания: PySide6 не удерживает
        ссылку на колбэк ``runJavaScript`` у фрейма — без нашей ссылки его
        собирает сборщик мусора, и результат никогда не приходит.
        """
        targets = self._serp_frames() or [self._main_frame()]
        parts: list = []
        state = {"pending": len(targets), "done": False, "cbs": []}

        def finish() -> None:
            if not state["done"]:
                state["done"] = True
                emit(parts)

        def make_cb():
            def cb(res):
                parts.append(res)      # результат фрейма — в общий список
                state["pending"] -= 1
                if state["pending"] <= 0:
                    finish()
            state["cbs"].append(cb)   # держим ссылку: иначе GC убьёт колбэк
            return cb

        for t in targets:
            try:
                run_one(t, make_cb())
            except Exception:
                state["pending"] -= 1
        QTimer.singleShot(timeout_ms, finish)

    def _inject_serp(self) -> None:
        """Инъекция чекбоксов во все фреймы-выдачи (идемпотентно)."""
        for fr in self._serp_frames():
            inject_checkbox_ui(fr)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        url = self.view.url().toString()
        if not is_image_search_url(url):
            return
        # выдача может быть во вложенном фрейме (Mail.ru), который грузится
        # ПОСЛЕ страницы-обёртки; плитки часто дорисовываются несколько секунд
        # (Google) — инъекция идемпотентна, повторяем несколько раз
        for ms in (0, 1500, 3500, 7000, 12000):
            QTimer.singleShot(ms, self._inject_serp)

    def _on_url_changed(self, url: QUrl) -> None:
        """Новый поиск/вертикаль без перезагрузки страницы — тоже выдача."""
        if not is_image_search_url(url.toString()):
            return
        # идемпотентно: если чекбоксы уже стоят — просто пройдётся скан
        self._inject_serp()
        for ms in (1500, 4000, 9000):
            QTimer.singleShot(ms, self._inject_serp)

    def _poll_checked_count(self) -> None:
        if not self.isVisible():
            return
        targets = self._serp_frames() or [self._main_frame()]
        counts: dict = {}
        cbs: list = []   # ссылки на колбэки (иначе GC убивает их для фреймов)

        def cb_factory(key):
            def cb(value):
                try:
                    counts[key] = int(value or 0)
                except (TypeError, ValueError):
                    counts[key] = 0
                self._on_poll_result(max(counts.values()))
            cbs.append(cb)
            return cb

        for i, t in enumerate(targets):
            try:
                t.runJavaScript("window.__IH_CB_COUNT || 0", cb_factory(i))
            except Exception:
                pass

    def _set_checked_count(self, count: int) -> None:
        suffix = f" ({count})" if count else ""
        self.btn_checked.setText(tr("ws.download_checked") + suffix)
        self.btn_save.setText(tr("ws.save") + suffix)

    def _on_poll_result(self, value) -> None:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = 0
        if count != self._checked_count:
            self._checked_count = count
            self._set_checked_count(count)
            self.btn_checked.setEnabled(count > 0)
            self.btn_save.setEnabled(count > 0)
            self.btn_clear.setEnabled(count > 0)
            self.checked_count_changed.emit(count)

    # ---------- перетрансляция при смене языка ----------

    def _retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка)."""
        self.query.setPlaceholderText(tr("ws.query_ph"))
        self.engine.setToolTip(tr("ws.engine_tip"))
        self.go_btn.setText(tr("ws.find"))
        self.collect_btn.setText(tr("ws.collect"))
        self.collect_btn.setToolTip(tr("ws.collect_tip"))
        self.btn_checked.setToolTip(tr("ws.download_checked_tip"))
        self.format_box.setToolTip(tr("ws.format_tip"))
        self.btn_save.setToolTip(tr("ws.save_tip", ext=self.current_ext()))
        self.btn_clear.setText(tr("ws.clear"))
        self.btn_clear.setToolTip(tr("ws.clear_tip"))
        self._set_checked_count(self._checked_count)
