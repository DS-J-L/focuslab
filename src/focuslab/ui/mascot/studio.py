"""Decorative paint layer for the compact session perch.

Everything is generated locally with Qt primitives: no runtime assets, web requests or
GPU effects.  This is intentionally separate from animation/behavior, which owns motion.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from focuslab.ui.mascot.renderer import paint_icon

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
    """A quiet charcoal stage lets the three original character palettes lead."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    panel = QRectF(2, 2, width - 4, height - 4)
    p.setClipPath(_rounded(panel, 16))
    bg = QLinearGradient(QPointF(0, 0), QPointF(width, height))
    bg.setColorAt(0, QColor("#343844"))
    bg.setColorAt(1, QColor("#252932"))
    p.fillRect(panel, QBrush(bg))
    for fraction, color in ((0.20, "#ACD98A"), (0.5, "#8CCAF2"), (0.8, "#F3D578")):
        _glow(p, QPointF(width * fraction, 139), 90, QColor(color), 17)
    p.setPen(QPen(QColor(255, 255, 255, 17), 1))
    p.drawLine(QPointF(14, 38), QPointF(width - 14, 38))
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(205, 218, 233, 45), 1))
    p.drawRoundedRect(panel, 16, 16)
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


def paint_action_pin(p: QPainter, x: float, icon: str, enabled: bool, focused: bool) -> None:
    """Keep function symbols below the perch, away from character artwork."""
    p.save()
    p.setOpacity(1.0 if enabled else 0.38)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFF5DF"))
    p.drawEllipse(QPointF(x, 238), 11, 11)
    paint_icon(p, icon, QPointF(x, 238), 7, on_belly=True)
    if focused:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor("#B8E8F4"))
        p.drawEllipse(QPointF(x, 238), 15, 15)
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
