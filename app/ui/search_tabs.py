"""Мультивкладки поиска — «как в браузере» внутри вкладки «Поиск картинок».

Каждая вложенная вкладка — самостоятельный WebSearch: своя строка поиска,
свой поисковик и свой встроенный браузер. Умеет то же, что браузер:

• «＋» — новая вкладка (Ctrl+T), поисковик берётся у текущей вкладки;
• крестик на вкладке — закрыть (Ctrl+W), последнюю заменяет свежая —
  поиск в программе никогда не остаётся без вкладки;
• правый клик по вкладке — меню: дублировать / закрыть / закрыть другие /
  закрыть справа;
• вкладки можно перетаскивать мышью.

Заголовок вкладки — короткое название выбранного поисковика, а цветной
кружок на вкладке — фирменный цвет его бренда (Яндекс — красный,
DuckDuckGo — оранжевый, Google — синий, Bing — зелёный): при поиске в
разных поисковиках вкладки видно мгновенно. Открытые вкладки (список
поисковиков) запоминаются и восстанавливаются при следующем запуске.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QMenu,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import applog, i18n
from app.core.i18n import tr
from app.core.image_saver import SAVE_FORMATS
from app.ui.web_search import ENGINES, WebSearch

MAX_TABS = 16   # каждая вкладка — целый браузер; больше не открываем
                # (поисковиков 13 — каждому хватит своей вкладки)
SETTINGS_KEY = "web/tabs"
_SEP = "|"      # разделитель списка поисковиков в настройках


def brand_icon(color: str) -> QIcon:
    """Кружок фирменного цвета поисковика — значок вкладки."""
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(2, 2, 12, 12)
    p.end()
    return QIcon(pm)


class SearchTabs(QWidget):
    """Контейнер вкладок поиска: пересылает сигналы активной жизни наружу."""

    images_found = Signal(list, str)          # (ссылки, URL страницы-источника)
    checked_count_changed = Signal(int)       # сколько плиток отмечено
    save_requested = Signal(list, str)        # (оригиналы отмеченных, referer)

    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)             # вкладки перетаскиваются мышью
        self.tabs.setTabsClosable(True)        # крестик на каждой вкладке
        self.tabs.setDocumentMode(True)        # плоские вкладки «как в браузере»
        lay.addWidget(self.tabs)

        # «＋» в правом углу полосы вкладок — новая вкладка
        self.btn_new = QToolButton()
        self.btn_new.setText("＋")
        self.btn_new.setAutoRaise(True)
        self.btn_new.setToolTip(tr("ws.tab_new_tip"))
        self.btn_new.clicked.connect(lambda: self.add_tab())
        self.tabs.setCornerWidget(self.btn_new, Qt.Corner.TopRightCorner)

        self.tabs.tabCloseRequested.connect(self._close_tab)
        bar = self.tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._tab_menu)

        # горячие клавиши как в браузере (работают, когда эта область на экране)
        sc_new = QShortcut(QKeySequence("Ctrl+T"), self)
        sc_new.activated.connect(lambda: self.add_tab())
        sc_close = QShortcut(QKeySequence("Ctrl+W"), self)
        sc_close.activated.connect(self.close_current)

        # восстановить вкладки прошлой сессии (список поисковиков)
        saved = str(QSettings("ImageHunter", "ImageHunter").value(SETTINGS_KEY, "") or "")
        names = [n for n in saved.split(_SEP) if n]
        restored = 0
        for name in names:
            if self.add_tab(engine_name=name, quiet=True) is not None:
                restored += 1
        if not restored:
            self.add_tab()
        if names:
            applog.event("log.event.search_tabs_restored", n=restored)

        i18n.signals.changed.connect(self._retranslate)

    # ---------- создание/закрытие вкладок ----------

    def add_tab(self, engine_name: str = "", focus: bool = True,
                quiet: bool = False) -> WebSearch | None:
        """Новая вкладка поиска; поисковик берётся у текущей вкладки
        (или передан явно по полному имени из ENGINES). None — предел вкладок."""
        if self.tabs.count() >= MAX_TABS:
            if not quiet:
                applog.event("log.event.search_tabs_limit", n=MAX_TABS)
            return None
        if not engine_name:
            cur = self.current_tab()
            if cur is not None:
                engine_name = cur.engine_meta()[0]
        ws = WebSearch()
        for idx, (name, _u, _s, _c) in enumerate(ENGINES):
            if name == engine_name:
                ws.engine.setCurrentIndex(idx)
                break
        # всё, что происходит внутри вкладки, пересылается наружу
        ws.images_found.connect(self.images_found)
        ws.save_requested.connect(self.save_requested)
        ws.checked_count_changed.connect(self.checked_count_changed)
        ws.engine.currentTextChanged.connect(lambda *_: self._refresh_tab(ws))

        index = self.tabs.addTab(ws, "")
        self._refresh_tab(ws)
        if focus:
            self.tabs.setCurrentIndex(index)
        self._persist()
        return ws

    def _close_tab(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count():
            return
        ws = self.tabs.widget(index)
        self.tabs.removeTab(index)
        ws.deleteLater()
        if self.tabs.count() == 0:
            # последнюю закрыли — как в браузере, но без закрытия программы:
            # остаётся одна свежая вкладка поиска
            self.add_tab(quiet=True)
        self._persist()

    def close_current(self) -> None:
        """Ctrl+W: закрыть активную вкладку."""
        self._close_tab(self.tabs.currentIndex())

    def _duplicate_tab(self, index: int) -> None:
        ws = self.tabs.widget(index)
        if ws is None:
            return
        engine = ws.engine_meta()[0]
        query = ws.query.text().strip()
        url = ws.view.url().toString()
        new = self.add_tab(engine_name=engine)
        if new is None:
            return
        if query:
            new.query.setText(query)
            new.search()          # тот же запрос тем же поисковиком заново
        elif url:
            new.view.load(url)    # открытая страница — просто скопировать

    def _close_others(self, index: int) -> None:
        for i in range(self.tabs.count() - 1, -1, -1):
            if i != index:
                self._close_tab(i)

    def _close_right(self, index: int) -> None:
        for i in range(self.tabs.count() - 1, index, -1):
            self._close_tab(i)

    # ---------- меню вкладки ----------

    def _tab_menu(self, pos) -> None:
        bar = self.tabs.tabBar()
        index = bar.tabAt(pos)
        menu = QMenu(self)
        act_new = menu.addAction(tr("ws.tab_new"))
        act_dup = act_close = act_others = act_right = None
        if index >= 0:
            act_dup = menu.addAction(tr("ws.tab_duplicate"))
            menu.addSeparator()
            act_close = menu.addAction(tr("ws.tab_close"))
            act_others = menu.addAction(tr("ws.tab_close_others"))
            act_right = menu.addAction(tr("ws.tab_close_right"))
        chosen = menu.exec(bar.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_new:
            self.add_tab()
        elif chosen is act_dup:
            self._duplicate_tab(index)
        elif chosen is act_close:
            self._close_tab(index)
        elif chosen is act_others:
            self._close_others(index)
        elif chosen is act_right:
            self._close_right(index)

    # ---------- заголовки и цвета вкладок ----------

    def _refresh_tab(self, ws: WebSearch) -> None:
        """Заголовок вкладки — поисковик, кружок — его фирменный цвет."""
        index = self.tabs.indexOf(ws)
        if index < 0:
            return
        name, _u, short, color = ws.engine_meta()
        self.tabs.setTabText(index, short)
        self.tabs.setTabIcon(index, brand_icon(color))
        self.tabs.setTabToolTip(index, name)
        self._persist()

    def _persist(self) -> None:
        """Список открытых поисковиков — в настройки (восстановим к запуску)."""
        names = [self.tabs.widget(i).engine_meta()[0]
                 for i in range(self.tabs.count()) if self.tabs.widget(i)]
        QSettings("ImageHunter", "ImageHunter").setValue(SETTINGS_KEY, _SEP.join(names))

    # ---------- наружный интерфейс (как у одиночного WebSearch) ----------

    def current_tab(self) -> WebSearch | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, WebSearch) else None

    def current_format(self) -> str:
        ws = self.current_tab()
        return ws.current_format() if ws else next(iter(SAVE_FORMATS))

    def current_query(self) -> str:
        ws = self.current_tab()
        return ws.query.text() if ws else ""

    # ---------- перетрансляция при смене языка ----------

    def _retranslate(self, *_args) -> None:
        self.btn_new.setToolTip(tr("ws.tab_new_tip"))
