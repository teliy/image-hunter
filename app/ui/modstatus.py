"""Виджет «работа модулей» в строке статуса (v0.8.20).

Пожелание: «сделай, чтобы можно было видеть в строке статуса процесс
и/или статус работы модулей, особенно модуля удаления ватермарков».

Справа в статус-баре (рядом с подписью вьюера) живёт этот виджет:
метка с текстом активности и полоса прогресса. Пока модули молчат, виджет
скрыт и места не занимает; первая же активность (установка модуля,
загрузка моделей, обработка пачки) появляется на ПОСТОЯННОМ месте —
открытие папки, поиск и прочие сообщения вьюера её не затирают: раньше
прогресс ватермарков жил в подписи вьюера и терялся при первом же
событии, а во время загрузки моделей замирал на «0/12» на минуты.

Поведение:

* ``activity(key, text, frac)`` — запомнить активность модуля ``key``;
  показывается последняя обновлённая (модули могут работать одновременно);
* доля ``frac`` 0..1 — видна полоса прогресса; ``-1`` — полоса скрыта;
* если активность не обновляется дольше 3 с, метка тикает
  « · N с» (v0.8.20): грузящиеся модели и pip не выглядят зависанием —
  видно, что процесс жив и сколько он уже идёт;
* ``finished(key)`` — активность снята; если других нет, виджет скрыт.

Здесь только виджет; мост — app/core/modstatus.py, тексты (i18n) —
у вьюера (в jet тексте активности) и один формат «секунд» здесь.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from app.core.i18n import tr

# тикающие секунды: начинается не сразу — короткие операции не мигают «0 с»
_ELAPSED_AFTER_S = 3


class ModuleStatusWidget(QWidget):
    """Активность модулей на постоянном месте статус-бара."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        self._bar = QProgressBar()
        self._bar.setFixedWidth(120)
        self._bar.setFixedHeight(12)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 8, 0)
        lay.setSpacing(6)
        lay.addWidget(self._label)
        lay.addWidget(self._bar)
        self.hide()   # пустой виджет места не занимает

        # активности модулей: key → (текст, доля, monotonic последней правки)
        self._items: dict[str, tuple[str, float, float]] = {}
        self._current = ""            # какой модуль показан сейчас
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ---------- мост (подключается в main_window) ----------

    def activity(self, key: str, text: str, frac: float) -> None:
        """Новая/обновлённая активность модуля ``key``."""
        self._items[key] = (text, frac, time.monotonic())
        self._current = key
        self._render()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def finished(self, key: str) -> None:
        """Модуль ``key`` закончил; без других активностей виджет скрыт."""
        self._items.pop(key, None)
        if self._current == key:
            self._current = next(iter(self._items), "")
        if self._items:
            self._render()
        else:
            self._reset()

    # ---------- отрисовка ----------

    def _render(self) -> None:
        """Показать текущую активность: текст, полоса, счётчик секунд."""
        item = self._items.get(self._current)
        if item is None:
            self._reset()
            return
        text, frac, t0 = item
        elapsed = time.monotonic() - t0
        if elapsed >= _ELAPSED_AFTER_S:
            text = text + tr("modstatus.elapsed", sec=int(elapsed))
        self._label.setText(text)
        if frac >= 0.0:
            # зажимаем сами: диапазон полосы 0..100, доля приходит из деления
            f = max(0.0, min(1.0, frac))
            self._bar.setValue(round(f * 100))
            self._bar.show()
        else:
            self._bar.hide()

    def _tick(self) -> None:
        """Секундный тик: раз в секунду перерисовать счётчик elapsed."""
        if self._items:
            self._render()

    def _reset(self) -> None:
        """Скрыть всё и остановить тики (активностей больше нет)."""
        self._items.clear()
        self._current = ""
        self._timer.stop()
        self._bar.hide()
        self._label.clear()
        self.hide()
