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
    rescan_checkbox_ui,
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
        # выдача картинок: iax/ia (актуально) или iar (старые сохранённые ссылки)
        have = lambda k: (query.get(k) or [""])[0]  # noqa: E731
        return "images" in (have("ia"), have("iax"), have("iar"))
    if host.endswith(("google.com", "google.ru", "google.by", "google.kz", "google.com.ua")):
        return (query.get("udm") or [""])[0] == "2" or path.startswith("/imgres")
    if host.endswith("bing.com"):
        return path.startswith("/images")
    return False


class WebSearch(QWidget):
    """Строка поиска + встроенный браузер + чекбоксы на плитках + сбор ссылок."""

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
        collect_image_urls(self.view.page(), self._on_collected)

    def download_checked(self) -> None:
        """Отправить в загрузки оригиналы отмеченных галочками плиток."""
        fetch_checked_selections(self.view.page(), self._on_checked)

    def save_checked(self) -> None:
        """Отмеченные плитки → перекодировать в выбранный формат → папка из «Моих картинок»."""
        fetch_checked_selections(self.view.page(), self._on_checked_save)

    def clear_checked(self) -> None:
        """Снять все отметки с плиток на текущей странице выдачи."""
        uncheck_all_selections(self.view.page())
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
