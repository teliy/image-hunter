"""Единая яркая подсветка выделения для всех списков, деревьев и таблиц.

Обычная тема Windows в режиме иконок красит выбранные плитки бледной
полупрозрачной заливкой — после «Выделить всё» (Ctrl+A) трудно понять,
что именно выделено, особенно на ленте миниатюр, где иконки перекрывают
подсветку. Здесь выделение красится плотным синим с белым текстом:

* активное окно  — насыщенный синий #1565d8 (белый текст);
* окно без фокуса (кликнули в другое место) — светлый голубой #8db4ef
  с тёмно-синим текстом: выделение остаётся заметным, но видно, что
  фокус ушёл;
* у плиток QListWidget добавлена тонкая рамка #0b47a1 — выделяется даже
  тёмная миниатюра, у которой синий фон за ней не читается.

Стиль ставится один раз на всё приложение (main.py → apply_app_style) и
действует на вкладку «Мои картинки» (лента миниатюр и дерево папок),
таблицу «Загрузок» и выпадающие списки — выделение выглядит одинаково
везде.
"""

from __future__ import annotations

SELECTION_QSS = """
QListWidget::item, QListView::item {
    border: 1px solid transparent; border-radius: 4px;
}
QListWidget::item:selected, QListView::item:selected {
    background: #1565d8; color: #ffffff; border: 1px solid #0b47a1;
}
QListWidget::item:selected:!active, QListView::item:selected:!active {
    background: #8db4ef; color: #0a2a55; border: 1px solid #5f8fd8;
}
QTreeWidget::item:selected, QTreeView::item:selected {
    background: #1565d8; color: #ffffff;
}
QTreeWidget::item:selected:!active, QTreeView::item:selected:!active {
    background: #8db4ef; color: #0a2a55;
}
QTableWidget::item:selected, QTableView::item:selected {
    background: #1565d8; color: #ffffff;
}
QTableWidget::item:selected:!active, QTableView::item:selected:!active {
    background: #8db4ef; color: #0a2a55;
}
"""


def apply_app_style(app) -> None:
    """Включить стиль выделения на всё приложение (один вызов из main.py)."""
    app.setStyleSheet(SELECTION_QSS)
