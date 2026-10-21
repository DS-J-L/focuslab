"""Decorative paint layer for the compact session perch.

Everything is generated locally with Qt primitives: no runtime assets, web requests or
GPU effects.  This is intentionally separate from animation/behavior, which owns motion.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

INK = QColor("#101725")
MINT = QColor("#72E5C5")
SKY = QColor("#8BB6FF")
GOLD = QColor("#FFE09A")


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _glow(p: QPainter, center: QPointF, radius: float, color: QColor, alpha: int) -> None:
    c = QColor(color)
    c.setAlpha(alpha)
    gradient = QRadialGradient(center, radius)
    gradient.setColorAt(0, c)
    c.setAlpha(0)
    gradient.setColorAt(1, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawEllipse(center, radius, radius)


def paint_scene(p: QPainter, width: int, height: int) -> None:
    """Draw a calm midnight-terrarium panel with restrained lighting and hairlines."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    panel = QRectF(2, 2, width - 4, height - 4)
    p.setClipPath(_rounded(panel, 16))

    bg = QLinearGradient(QPointF(0, 0), QPointF(width, height))
    bg.setColorAt(0, QColor("#202D43"))
    bg.setColorAt(0.52, QColor("#161F31"))
    bg.setColorAt(1, QColor("#0F1726"))
    p.fillRect(panel, bg)

    _glow(p, QPointF(80, 96), 92, QColor("#F17C7B"), 38)
    _glow(p, QPointF(153, 103), 96, QColor("#7D9FFE"), 40)
    _glow(p, QPointF(232, 100), 92, QColor("#F5D16E"), 38)

    # A subtly illuminated perch, without a busy full-scene grid.
    p.setPen(QPen(QColor(255, 255, 255, 12), 1))
    p.drawLine(QPointF(14, 38), QPointF(width - 14, 38))
    for x, y, radius, opacity in (
        (28, 59, 1.4, 55), (63, 43, 1.0, 65), (125, 66, 1.0, 45),
        (179, 57, 1.5, 60), (264, 50, 1.0, 70), (278, 96, 1.3, 40),
        (30, 126, 1.0, 40), (258, 137, 1.0, 45),
    ):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(218, 234, 255, opacity))
        p.drawEllipse(QPointF(x, y), radius, radius)

    # Thin arc silhouettes suggest a little glass greenhouse around the birds.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(207, 226, 251, 18), 1))
    p.drawArc(QRectF(23, 45, 254, 200), 28 * 16, 124 * 16)
    p.drawArc(QRectF(33, 59, 234, 167), 19 * 16, 148 * 16)

    brand_font = QFont()
    brand_font.setPixelSize(9)
    brand_font.setWeight(QFont.Weight.DemiBold)
    brand_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
    p.setFont(brand_font)
    p.setPen(QColor("#7F93B1"))
    p.drawText(QRectF(156, 12, 76, 18), Qt.AlignmentFlag.AlignRight, "FOCUSLAB")
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(176, 209, 245, 38), 1))
    p.drawRoundedRect(panel, 16, 16)
    p.setPen(QPen(QColor(255, 255, 255, 18), 1))
    p.drawLine(QPointF(17, 3.5), QPointF(width - 17, 3.5))
    p.restore()


def paint_seat(p: QPainter, x: float, y: float, hovered: bool, enabled: bool) -> None:
    """Provide a soft spotlight and a responsive halo without moving the click target."""
    p.save()
    color = QColor("#C7E8FF") if enabled else QColor("#8995A5")
    _glow(p, QPointF(x, y - 47), 43 if hovered else 35, color, 70 if hovered else 22)
    if hovered and enabled:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(216, 234, 255, 115), 1.25))
        p.drawEllipse(QPointF(x, y - 42), 36, 47)
    p.restore()


def paint_status_light(p: QPainter, state: str) -> None:
    colors = {
        "focusing": MINT,
        "paused": GOLD,
        "break": SKY,
    }
    color = colors.get(state, MINT)
    p.save()
    _glow(p, QPointF(19, 18), 10, color, 95)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(19, 18), 3.2, 3.2)
    p.restore()


def paint_progress(p: QPainter, rect: QRectF, fraction: float | None, state: str) -> None:
    """A quiet goal indicator, shown only when the session has a target duration."""
    if fraction is None:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QRectF(rect.left() + 13, rect.bottom() - 7.0, rect.width() - 26, 2.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#36445B"))
    p.drawRoundedRect(track, 1.25, 1.25)
    fraction = max(0.0, min(1.0, fraction))
    if fraction:
        bar = QRectF(track.left(), track.top(), track.width() * fraction, track.height())
        color = GOLD if state == "paused" else SKY if state == "break" else MINT
        p.setBrush(color)
        p.drawRoundedRect(bar, 1.25, 1.25)
    p.restore()
