"""Вкладка «Журнал»: хроника работы программы в человеческом виде.

Здесь виден ход работы: какая папка открыта, что найдено поиском,
какие файлы перетаскиваются мышью и куда, сколько скачано/сохранено
и какие ошибки случились. Строки приходят из applog (мост logging → Qt),
поэтому события из рабочих потоков появляются в журнале без задержек.

Кнопки: «Очистить» и «Копировать всё» (в буфер обмена — удобно приложить
к сообщению об ошибке). Ошибки выделяются красным, предупреждения —
оранжевым. Журнал ограничен 5000 последних строк, автопрокрутка вниз
работает, только пока пользователь стоит в конце — прокрутку вверх
не отбираем.
"""

from __future__ import annotations

import html

from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core import applog
from app.core.i18n import tr

_MAX_LINES = 5000

_LEVEL_COLOR = {
    10: "#7a7a7a",   # DEBUG    — серый
    20: None,        # INFO     — обычный цвет текста
    30: "#b26a00",   # WARN     — оранжевый
    40: "#c62828",   # ERROR    — красный
}


class LogView(QWidget):
    """Панель журнала: заголовок + кнопки + текстовое поле хроники."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._i18n_buttons: list[tuple[QToolButton, str, str]] = []

        head = QHBoxLayout()
        head.setContentsMargins(8, 4, 8, 4)
        self._title = QLabel(tr("log.title"))
        head.addWidget(self._title)
        head.addStretch(1)

        self.btn_copy = QToolButton()
        self.btn_copy.setText(tr("log.copy"))
        self.btn_copy.setToolTip(tr("log.copy_tip"))
        self.btn_copy.setAutoRaise(True)
        self.btn_copy.clicked.connect(self.copy_all)
        head.addWidget(self.btn_copy)
        self._i18n_buttons.append((self.btn_copy, "log.copy", "log.copy_tip"))

        self.btn_clear = QToolButton()
        self.btn_clear.setText(tr("log.clear"))
        self.btn_clear.setToolTip(tr("log.clear_tip"))
        self.btn_clear.setAutoRaise(True)
        self.btn_clear.clicked.connect(self.clear_log)
        head.addWidget(self.btn_clear)
        self._i18n_buttons.append((self.btn_clear, "log.clear", "log.clear_tip"))

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(_MAX_LINES)
        self.text.setPlaceholderText(tr("log.empty"))
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addWidget(self.text, 1)

        # Ctrl+C в поле — копировать выделенные строки (штатно), Ctrl+A — всё
        sc = QShortcut(QKeySequence.Copy, self.text)
        sc.activated.connect(self.copy_all)

        applog.bridge.record.connect(self._on_record)
        self._scroll = self.text.verticalScrollBar()
        applog.event("log.event.tab_opened")

    # ---------- приём строк из журнала ----------

    def _on_record(self, level: int, line: str) -> None:
        """Дописать строку журнала, не отбирая у пользователя прокрутку вверх."""
        at_bottom = self._scroll.value() >= self._scroll.maximum() - 4
        color = _LEVEL_COLOR.get(level)
        if color:
            self.text.appendHtml(
                f"<span style='color:{color}'>{html.escape(line)}</span>")
        else:
            self.text.appendPlainText(line)
        if at_bottom:
            self._scroll.setValue(self._scroll.maximum())

    # ---------- кнопки ----------

    def clear_log(self) -> None:
        self.text.clear()
        applog.event("log.cleared")

    def copy_all(self) -> None:
        text = self.text.toPlainText()
        QApplication.clipboard().setText(text)
        applog.event("log.copied", n=text.count("\n") + (1 if text else 0))

    # ---------- смена языка ----------

    def retranslate(self, *_args) -> None:
        """Обновить статические надписи (i18n вызывает при смене языка)."""
        self._title.setText(tr("log.title"))
        for b, text_key, tip_key in self._i18n_buttons:
            b.setText(tr(text_key))
            b.setToolTip(tr(tip_key))
        self.text.setPlaceholderText(tr("log.empty"))
