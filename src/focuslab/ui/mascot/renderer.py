"""Reference-preserving image rigs, the perch, action pins and speech bubbles.

Faces keep their original artwork. Only registered eye/mouth patches change; the
head silhouette, feather texture and feet remain stable during small movements.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from focuslab.ui.mascot.animation import Pose
from focuslab.ui.mascot.artwork import character_art, eye_frame

HEAD_Y = -73.0
TOP_Y = -133.0  # clears the cockatiel's separate crest, including its sway
INK = QColor("#20222B")


@dataclass(frozen=True)
class Plumage:
    body: str
    outline: str
    wing: str
    belly: str
    beak: str = "#F59E2B"
    beak_outline: str = "#B5651A"
    character_id: str = "peach-lovebird"


# Legacy names retain the existing button/personality mapping.
RED = Plumage("#B8D77D", "#678856", "#69A982", "#F4AC85")
BLUE = Plumage("#83CCF1", "#234A85", "#467BD0", "#CCEAF8", character_id="sky-parrot")
YELLOW = Plumage(
    "#F9DF7D", "#B68F43", "#E5C868", "#FFF0CD", "#8D8177", "#61594E",
    character_id="lemon-cockatiel",
)


def _pen(color: QColor | str, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _feather(length: float, width: float) -> QPainterPath:
    path = QPainterPath(QPointF(0, 0))
    path.quadTo(width, length * 0.45, 0, length)
    path.quadTo(-width, length * 0.45, 0, 0)
    return path


def character_top(plumage: Plumage) -> float:
    art = character_art(plumage.character_id)
    return min(-103.0, art.crest.top()) if art.crest is not None else -103.0


def paint_bird(p: QPainter, pose: Pose, plumage: Plumage, emblem: str | None = None) -> None:
    """One continuous rig shared by the perch, collapsed preview and flight window."""
    art = character_art(plumage.character_id)
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.translate(pose.x, pose.y)
    p.setOpacity(p.opacity() * max(0.0, min(1.0, pose.alpha)))
    p.scale(pose.scale, pose.scale)
    p.rotate(max(-16.0, min(16.0, pose.tilt)))
    if art.fallback is not None:
        p.drawImage(QRectF(-61, -122, 122, 122), art.fallback)
        p.restore()
        return
    parts = art.parts
    # Tail and far wing are behind the torso. In flight the unfurled artwork is
    # articulated continuously, rather than dissolving unrelated wing images.
    p.save()
    p.translate(13, -29)
    p.rotate(-28 + pose.crest * 0.30)
    p.drawImage(QRectF(-7, -3, 19, 30), parts[5])
    p.restore()
    _wing(p, parts, -1, pose.wing_l, pose.airborne)

    # The toes do not stretch with breathing. Their contact baseline stays at y=0.
    tuck = max(0.0, min(1.0, pose.airborne))
    for x, image in ((-11, parts[6]), (11, parts[7])):
        p.save()
        p.translate(x * (1 - tuck * 0.25), -tuck * 5)
        p.scale(1 - tuck * 0.25, 1 - tuck * 0.25)
        p.drawImage(QRectF(-8.5, -11, 17, 11), image)
        p.restore()

    squash = max(0.86, min(1.12, pose.squash))
    p.save()
    p.scale((1 + 0.045 * pose.puff) / math.sqrt(squash), squash)
    p.drawImage(QRectF(-32, -59, 64, 56), parts[1])
    p.restore()
    _wing(p, parts, 1, pose.wing_r, pose.airborne)

    p.save()
    p.translate(max(-1, min(1, pose.turn)) * 2, (1 - squash) * 10)
    p.translate(0, -47)
    p.rotate(max(-9, min(9, pose.head_tilt)))
    p.translate(0, 47)
    head_height = 62 * art.head.height() / art.head.width()
    head_rect = QRectF(-31, -103, 62, head_height)
    index = eye_frame(pose.eye_open, pose.eyes)
    p.drawImage(head_rect, art.faces[int(pose.beak_open > 0.3)][index])
    if art.crest is not None:
        # The independent tuft follows the head with its own slow secondary sway.
        p.save()
        p.translate(4, -97)
        p.rotate(max(-12, min(12, pose.crest * 0.55)))
        p.translate(-4, 97)
        p.drawImage(art.crest, parts[8])
        p.restore()
    p.restore()
    p.restore()


def _wing(p: QPainter, parts: tuple, side: int, angle: float, airborne: float) -> None:
    p.save()
    p.translate(side * 25, -46)
    p.scale(side, 1)
    if side < 0:
        p.scale(0.85, 0.85)
    if airborne > 0.12:
        p.rotate(52 - max(0, min(110, angle)) * 1.12)
        p.drawImage(QRectF(-4, -6, 58, 36), parts[4])
    else:
        p.rotate(-max(0, min(110, angle)) * 0.70 - 7)
        p.drawImage(QRectF(-8, -3, 20, 35), parts[2])
    p.restore()


# Perch, plaque and bubbles -------------------------------------------------------------
WOOD = QColor("#7A4A26")
WOOD_DARK = QColor("#4E2E16")
WOOD_LIGHT = QColor("#9A6638")
LEAF = QColor("#5DAE5A")


def paint_branch(p: QPainter, rect: QRectF) -> None:
    """A subtly three-dimensional bough with one little green sprig."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 52))
    p.drawRoundedRect(rect.translated(0, 4), 8, 8)
    p.setPen(_pen(WOOD_DARK, 1.5))
    wood = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.bottom()))
    wood.setColorAt(0, QColor("#BD8251"))
    wood.setColorAt(0.28, QColor("#935C38"))
    wood.setColorAt(0.75, QColor("#633D2B"))
    wood.setColorAt(1, QColor("#4B3028"))
    p.setBrush(wood)
    p.drawRoundedRect(rect, 8, 8)
    p.setPen(_pen(QColor(255, 216, 156, 100), 1.3))
    p.drawLine(
        QPointF(rect.left() + 13, rect.top() + 3),
        QPointF(rect.right() - 15, rect.top() + 3),
    )
    p.setPen(_pen(QColor("#533523"), 1.4))
    for start, end, offset in ((0.1, 0.22, 8), (0.44, 0.51, 10), (0.67, 0.84, 8)):
        p.drawLine(
            QPointF(rect.left() + rect.width() * start, rect.top() + offset),
            QPointF(rect.left() + rect.width() * end, rect.top() + offset - 1),
        )
    sprig = QPointF(rect.right() - 21, rect.top() + 2)
    tip = sprig + QPointF(11, -13)
    p.setPen(_pen(QColor("#567348"), 2.4))
    p.drawLine(sprig, tip)
    for dx, angle in ((-5, -115), (5, -165)):
        p.save()
        p.translate(tip + QPointF(dx, -1))
        p.rotate(angle)
        leaf = QLinearGradient(QPointF(0, 0), QPointF(0, 13))
        leaf.setColorAt(0, QColor("#B9EEA0"))
        leaf.setColorAt(1, QColor("#52916B"))
        p.setBrush(leaf)
        p.setPen(_pen(QColor("#376F50"), 0.8))
        p.drawPath(_feather(13, 4.2))
        p.restore()
    p.restore()


def paint_plaque(p: QPainter, rect: QRectF, strings: tuple[float, float], top: float) -> None:
    """Quiet floating clock card, connected to the perch by two silver threads."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(_pen(QColor("#64768F"), 1.5))
    for x in strings:
        p.drawLine(QPointF(x, top), QPointF(x, rect.top() + 2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 70))
    p.drawRoundedRect(rect.translated(0, 2.5), 11, 11)
    surface = QLinearGradient(
        QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom())
    )
    surface.setColorAt(0, QColor("#303E56"))
    surface.setColorAt(0.45, QColor("#212C40"))
    surface.setColorAt(1, QColor("#172237"))
    p.setPen(_pen(QColor("#6D83A0"), 1.25))
    p.setBrush(surface)
    p.drawRoundedRect(rect, 11, 11)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(QColor(225, 239, 255, 35), 0.9))
    p.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 9, 9)
    p.restore()



def paint_bubble(p: QPainter, tip: QPointF, icon: str) -> None:
    "A white speech bubble whose tail points at ``tip`` (the top of a parrot's head)."
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(tip.x() - 20, tip.y() - 44, 40, 34)
    path = QPainterPath()
    path.addRoundedRect(box, 15, 15)
    tail = QPainterPath(QPointF(tip.x() - 6, box.bottom() - 2))
    tail.lineTo(tip.x() + 2, tip.y() - 2)
    tail.lineTo(tip.x() + 7, box.bottom() - 2)
    tail.closeSubpath()
    p.setPen(_pen(QColor("#D8DCE4"), 1.2))
    p.setBrush(QColor("white"))
    p.drawPath(path.united(tail))
    paint_icon(p, icon, box.center(), 9)
    p.restore()


def paint_icon(p: QPainter, icon: str, c: QPointF, r: float, on_belly: bool = False) -> None:
    """Session action icons, drawn on a parrot's belly and in speech bubbles."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    red = QColor("#A3221B") if on_belly else QColor("#E5392F")
    if icon == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(red)
        for dx in (-0.55, 0.2):
            p.drawRoundedRect(QRectF(c.x() + dx * r, c.y() - r * 0.8, r * 0.35, r * 1.6), 1.5, 1.5)
    elif icon == "play":
        path = QPainterPath(c + QPointF(-0.5 * r, -0.75 * r))
        path.lineTo(c + QPointF(0.75 * r, 0))
        path.lineTo(c + QPointF(-0.5 * r, 0.75 * r))
        path.closeSubpath()
        p.setPen(_pen(red, 1.5))
        p.setBrush(red)
        p.drawPath(path)
    elif icon == "stop":
        p.setPen(_pen(QColor("#E5392F"), 2.4) if on_belly else Qt.PenStyle.NoPen)
        p.setBrush(Qt.BrushStyle.NoBrush if on_belly else red)
        p.drawRoundedRect(QRectF(c.x() - 0.7 * r, c.y() - 0.7 * r, 1.4 * r, 1.4 * r), 2, 2)
    elif icon in ("cup", "back"):
        brown = QColor("#8A5A2B")
        p.setPen(_pen(brown, 1.6))
        p.setBrush(QColor("#F6E3C6") if not on_belly else QColor("#FFF6E0"))
        body = QRectF(c.x() - 0.75 * r, c.y() - 0.3 * r, 1.25 * r, 1.0 * r)
        p.drawRoundedRect(body, 2.5, 2.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(body.right() - 2, body.top() + 1, 0.6 * r, 0.55 * r), -90 * 16, 180 * 16)
        if icon == "back":  # the break is on: a curved arrow back to work
            p.setPen(_pen(QColor("#3E72E6"), 1.8))
            arc = QRectF(c.x() - 0.6 * r, c.y() - 1.3 * r, 1.2 * r, 0.9 * r)
            p.drawArc(arc, 0, 180 * 16)
            head = QPointF(arc.left(), arc.center().y())
            p.drawLine(head, head + QPointF(-2.5, -3))
            p.drawLine(head, head + QPointF(2.5, -3))
        else:  # steam
            p.setPen(_pen(QColor("#B9A58F"), 1.3))
            for dx in (-0.3, 0.15):
                x = c.x() + dx * r
                steam = QPainterPath(QPointF(x, c.y() - 0.45 * r))
                steam.cubicTo(x - 2, c.y() - 0.75 * r, x + 2, c.y() - 0.95 * r, x, c.y() - 1.25 * r)
                p.drawPath(steam)
    p.restore()


def paint_emote(p: QPainter, emote: str, head: QPointF, t: float) -> None:
    """Little symbols above a parrot's head; ``t`` (seconds shown) drives their own motion."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    drift = math.sin(t * 3.0)
    if emote == "zzz":
        font = QFont()
        font.setBold(True)
        p.setPen(QColor("#E8ECF4"))
        for i, size in enumerate((9, 11, 13)):
            phase = (t * 0.6 + i / 3) % 1
            font.setPixelSize(size)
            p.setFont(font)
            p.setOpacity(1 - phase * 0.6)
            pos = head + QPointF(14 + i * 7 + drift * 1.5, -16 - i * 9 - phase * 4)
            p.drawText(pos, "z" if i < 2 else "Z")
    elif emote == "note":
        p.setPen(_pen(QColor("#FFD24A"), 2))
        p.setBrush(QColor("#FFD24A"))
        base = head + QPointF(20 + drift * 2, -18 - (t * 8) % 6)
        p.drawEllipse(base, 3.2, 2.5)
        p.drawLine(base + QPointF(3, 0), base + QPointF(3, -12))
        p.drawLine(base + QPointF(3, -12), base + QPointF(8, -9))
    elif emote == "alert":
        p.setPen(_pen(QColor("#FFD24A"), 3))
        top = head + QPointF(-22, -26 - abs(drift) * 2)
        p.drawLine(top, top + QPointF(0, 10))
        p.drawPoint(top + QPointF(0, 15))
        for dx, dy in ((-7, 2), (7, 2)):
            p.setPen(_pen(QColor("#FFD24A"), 1.6))
            p.drawLine(top + QPointF(dx, dy), top + QPointF(dx * 1.5, dy - 4))
    elif emote == "anger":
        p.setPen(_pen(QColor("#FF4D4D"), 2.4))
        c = head + QPointF(20, -24)
        pulse = 1 + 0.15 * abs(drift)
        for angle in (45, 135, 225, 315):
            rad = math.radians(angle)
            d = QPointF(math.cos(rad), math.sin(rad)) * 3 * pulse
            p.drawLine(c + d, c + d * 2.2)
    elif emote == "dots":
        box = QRectF(head.x() - 18, head.y() - 50, 36, 22)
        p.setPen(_pen(QColor("#D8DCE4"), 1.2))
        p.setBrush(QColor("white"))
        p.drawRoundedRect(box, 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(INK)
        for i in range(3):
            lift = 1.5 * math.sin(t * 6 - i)
            p.drawEllipse(box.center() + QPointF((i - 1) * 8, -max(0.0, lift)), 2, 2)
    elif emote == "heart":
        c = head + QPointF(18, -26 - (t * 6) % 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FF5C7A"))
        heart = QPainterPath(c + QPointF(0, 5))
        heart.cubicTo(c + QPointF(-9, -1), c + QPointF(-4, -8), c + QPointF(0, -3))
        heart.cubicTo(c + QPointF(4, -8), c + QPointF(9, -1), c + QPointF(0, 5))
        p.drawPath(heart)
    elif emote == "sparkle":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#FFE27A")))
        for dx, dy, size in ((-20, -20, 4), (20, -26, 5), (4, -36, 3)):
            c = head + QPointF(dx, dy)
            k = size * (0.7 + 0.3 * abs(math.sin(t * 5 + dx)))
            star = QPainterPath(c + QPointF(0, -k))
            for px, py in ((0.25, -0.25), (1, 0), (0.25, 0.25), (0, 1), (-0.25, 0.25), (-1, 0)):
                star.lineTo(c + QPointF(px * k, py * k))
            star.lineTo(c + QPointF(-0.25 * k, -0.25 * k))
            star.closeSubpath()
            p.drawPath(star)
    p.restore()
