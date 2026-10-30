"""Иконка приложения Image Hunter: «фотография в рамке с лупой».

Иконка рисуется программно (QPainter) — один и тот же код работает и для
генерации файлов-ресурсов (scripts/make_icon.py сохраняет PNG 512×512 и
многоразмерный ICO в app/resources/), и как запасной путь: если файлов
рядом с программой не оказалось, значок собирается прямо в памяти и
приложение всё равно не остаётся без иконки.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

RES_DIR = Path(__file__).resolve().parent.parent / "resources"

_cached: QIcon | None = None


def icon() -> QIcon:
    """Иконка приложения: ICO из ресурсов → PNG из ресурсов → рисуем в памяти."""
    global _cached
    if _cached is not None:
        return _cached
    ic = QIcon()
    ico, png = RES_DIR / "app_icon.ico", RES_DIR / "app_icon.png"
    if ico.exists():
        ic = QIcon(str(ico))
    elif png.exists():
        ic = QIcon(str(png))
    if ic.isNull():
        ic = QIcon(paint_pixmap(256))
    _cached = ic
    return ic


def paint_pixmap(size: int) -> QPixmap:
    """Нарисовать значок «фото в рамке с лупой» стороной size px.

    Композиция (масштабируется от 512): белая карточка-фотография со
    скруглением, внутри небо с солнцем и зелёные холмы, поверх справа
    снизу — лупа («hunter»). Всё рисуется векторно, поэтому значок
    остаётся чётким на любом размере.
    """
    s = max(16, int(size))
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    k = s / 512.0                      # множитель от «канонического» размера

    # --- белая карточка-фотография со скруглёнными углами и мягкой тенью ---
    card = QRectF(20 * k, 12 * k, 472 * k, 488 * k)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 60))
    p.drawRoundedRect(card.translated(0, 10 * k), 88 * k, 88 * k)
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(card, 88 * k, 88 * k)

    # --- «фото»: небо + солнце + холмы, внутри карточки ---
    photo = QRectF(52 * k, 44 * k, 408 * k, 330 * k)
    path = QPainterPath()
    path.addRoundedRect(photo, 56 * k, 56 * k)
    p.save()
    p.setClipPath(path)

    sky = QLinearGradient(photo.topLeft(), photo.bottomLeft())
    sky.setColorAt(0.0, QColor("#2f7fd0"))
    sky.setColorAt(1.0, QColor("#9fd9f6"))
    p.fillRect(photo, QBrush(sky))

    p.setBrush(QColor("#ffd54f"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(352 * k, 140 * k), 52 * k, 52 * k)

    back = QPainterPath()
    back.moveTo(photo.left(), photo.bottom())
    back.quadTo(photo.center().x(), photo.top() + 150 * k, photo.right(), photo.bottom())
    p.setBrush(QColor("#2e7d4f"))
    p.drawPath(back)

    front = QPainterPath()
    front.moveTo(photo.left(), photo.bottom())
    front.quadTo(photo.left() + 150 * k, photo.bottom() - 130 * k,
                 photo.right() - 40 * k, photo.bottom())
    p.setBrush(QColor("#43a05e"))
    p.drawPath(front)
    p.restore()

    # --- лупа: стеклянная линза с бликом и ручка ---
    lens_c = QPointF(322 * k, 328 * k)
    lens_r = 96 * k
    p.save()
    p.translate(lens_c)
    grad = QConicalGradient(0, 0, 45)
    grad.setColorAt(0.00, QColor("#4c5a63"))
    grad.setColorAt(0.35, QColor("#263238"))
    grad.setColorAt(0.70, QColor("#37474f"))
    grad.setColorAt(1.00, QColor("#4c5a63"))
    p.setPen(QPen(QBrush(grad), 30 * k))
    p.setBrush(QColor(205, 235, 250, 150))
    p.drawEllipse(QPointF(0, 0), lens_r, lens_r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 110))
    p.drawEllipse(QPointF(-lens_r * 0.38, -lens_r * 0.42),
                  lens_r * 0.30, lens_r * 0.18)
    p.restore()

    p.setPen(QPen(QColor("#263238"), 34 * k, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(lens_c.x() + lens_r * 0.78, lens_c.y() + lens_r * 0.78),
               QPointF(452 * k, 452 * k))

    p.end()
    return pm
