"""Вкладка «Поиск картинок»: встроенный браузер поисковиков + сбор ссылок.

Два способа отправить картинки на вкладку «Загрузки»:
1. «Собрать ссылки» — все картинки текущей страницы выдачи (превью);
2. «Скачать отмеченные» — только отмеченные галочками плитки, причём
   для каждой берётся большой оригинал (origUrl / img_url), а не превью.
"""

from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, urlparse

from PySide6.QtCore import QTimer, QUrl, Signal
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

from app.core.extractor import (
    collect_image_urls,
    fetch_checked_selections,
    inject_checkbox_ui,
    rescan_checkbox_ui,
)

ENGINES = [
    ("Яндекс.Картинки", "https://ya.ru/images/search?text={}"),
    ("DuckDuckGo (safe)", "https://safe.duckduckgo.com/?q={}&iar=images&kp=1&t=h_"),
    ("Google Картинки", "https://www.google.com/search?q={}&udm=2"),
    ("Bing Картинки", "https://www.bing.com/images/search?q={}"),
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
    if any(host == h or host.endswith("." + h) for h in _YANDEX_HOSTS):
        return path.startswith("/images")
    if host.endswith("duckduckgo.com"):
        return (query.get("iar") or [""])[0] == "images"
    if host.endswith(("google.com", "google.ru", "google.by", "google.kz", "google.com.ua")):
        return (query.get("udm") or [""])[0] == "2" or path.startswith("/imgres")
    if host.endswith("bing.com"):
        return path.startswith("/images")
    return False


class WebSearch(QWidget):
    """Строка поиска + встроенный браузер + чекбоксы на плитках + сбор ссылок."""

    images_found = Signal(list, str)  # (ссылки, URL страницы-источника)
    checked_count_changed = Signal(int)  # сколько плиток отмечено

    def __init__(self, parent=None):
        super().__init__(parent)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)

        self.query = QLineEdit()
        self.query.setPlaceholderText("Поисковый запрос… (Enter — искать)")
        self.query.returnPressed.connect(self.search)

        self.engine = QComboBox()
        self.engine.addItems([name for name, _ in ENGINES])
        self.engine.setToolTip("Поисковая система")

        go = QToolButton()
        go.setText("Найти")
        go.clicked.connect(self.search)

        collect = QToolButton()
        collect.setText("📋 Собрать ссылки")
        collect.setToolTip(
            "Собрать ссылки на картинки (превью) с текущей страницы выдачи "
            "и отправить их на вкладку «Загрузки»"
        )
        collect.clicked.connect(self.collect)

        self.btn_checked = QToolButton()
        self.btn_checked.setText("⬇ Скачать отмеченные")
        self.btn_checked.setToolTip(
            "На плитках выдачи есть оранжевые чекбоксы: отметьте нужные картинки —\n"
            "здесь появится счётчик, а по кнопке скачаются большие оригиналы"
        )
        self.btn_checked.setEnabled(False)
        self.btn_checked.clicked.connect(self.download_checked)

        bar.addWidget(self.query, 1)
        bar.addWidget(self.engine)
        bar.addWidget(go)
        bar.addWidget(collect)
        bar.addWidget(self.btn_checked)

        self.view = QWebEngineView()
        self.view.setUrl(QUrl("https://ya.ru/images/"))
        self.view.loadFinished.connect(self._on_load_finished)

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

    # ---------- действия ----------

    def search(self) -> None:
        text = self.query.text().strip()
        if not text:
            self.query.setFocus()
            return
        template = ENGINES[self.engine.currentIndex()][1]
        self.view.load(QUrl(template.format(quote_plus(text))))

    def collect(self) -> None:
        collect_image_urls(self.view.page(), self._on_collected)

    def download_checked(self) -> None:
        """Отправить в загрузки оригиналы отмеченных галочками плиток."""
        fetch_checked_selections(self.view.page(), self._on_checked)

    # ---------- внутреннее ----------

    def _on_collected(self, urls: list[str]) -> None:
        if not urls:
            self._info_no_links()
            return
        self.images_found.emit(urls, self.view.url().toString())

    def _on_checked(self, items: list[dict]) -> None:
        best = [it["best"] for it in items if it.get("best")]
        if not best:
            QMessageBox.information(
                self,
                "Image Hunter",
                "Нет отмеченных картинок.\n\n"
                "Отметьте оранжевыми галочками плитки с нужными картинками "
                "прямо на странице выдачи — на кнопке появится счётчик.",
            )
            return
        self.images_found.emit(best, self.view.url().toString())

    def _info_no_links(self) -> None:
        QMessageBox.information(
            self,
            "Image Hunter",
            "Ссылки не найдены.\n\nПодсказки:\n• дождитесь полной загрузки выдачи;\n"
            "• прокрутите страницу вниз, чтобы подгрузились миниатюры;\n"
            "• если Яндекс показывает капчу — введите её прямо здесь, во встроенном браузере.",
        )

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        url = self.view.url().toString()
        if not is_image_search_url(url):
            return
        page = self.view.page()
        inject_checkbox_ui(page)
        # плитки часто рисуются позже основного события загрузки
        QTimer.singleShot(1500, lambda: rescan_checkbox_ui(page))
        QTimer.singleShot(4000, lambda: rescan_checkbox_ui(page))

    def _poll_checked_count(self) -> None:
        if not self.isVisible():
            return
        try:
            self.view.page().runJavaScript(
                "window.__IH_CB_COUNT || 0", self._on_poll_result
            )
        except Exception:
            pass

    def _on_poll_result(self, value) -> None:
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            count = 0
        if count != self._checked_count:
            self._checked_count = count
            self.btn_checked.setText(
                f"⬇ Скачать отмеченные ({count})" if count else "⬇ Скачать отмеченные"
            )
            self.btn_checked.setEnabled(count > 0)
            self.checked_count_changed.emit(count)
