"""Вкладка «Поиск картинок»: встроенный браузер поисковиков + сбор ссылок."""

from __future__ import annotations

from urllib.parse import quote_plus

from PySide6.QtCore import QUrl, Signal
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

from app.core.extractor import collect_image_urls

ENGINES = [
    ("Яндекс.Картинки", "https://ya.ru/images/search?text={}"),
    ("DuckDuckGo (safe)", "https://safe.duckduckgo.com/?q={}&iar=images&kp=1&t=h_"),
    ("Google Картинки", "https://www.google.com/search?q={}&udm=2"),
    ("Bing Картинки", "https://www.bing.com/images/search?q={}"),
]


class WebSearch(QWidget):
    """Строка поиска + встроенный браузер + кнопка «Собрать ссылки»."""

    images_found = Signal(list, str)  # (ссылки, URL страницы-источника)

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
            "Собрать ссылки на картинки с текущей страницы выдачи "
            "и отправить их на вкладку «Загрузки»"
        )
        collect.clicked.connect(self.collect)

        bar.addWidget(self.query, 1)
        bar.addWidget(self.engine)
        bar.addWidget(go)
        bar.addWidget(collect)

        self.view = QWebEngineView()
        self.view.setUrl(QUrl("https://ya.ru/images/"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)

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

    def _on_collected(self, urls: list[str]) -> None:
        if not urls:
            QMessageBox.information(
                self,
                "Image Hunter",
                "Ссылки не найдены.\n\nПодсказки:\n• дождитесь полной загрузки выдачи;\n"
                "• прокрутите страницу вниз, чтобы подгрузились миниатюры;\n"
                "• если Яндекс показывает капчу — введите её прямо здесь, во встроенном браузере.",
            )
            return
        self.images_found.emit(urls, self.view.url().toString())
