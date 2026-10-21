"""QPainter drawing of the parrots, the branch, the time plaque and speech bubbles.

Everything is drawn from shapes rather than image files, so the parrots stay sharp at any
display scale and every body part can move on its own. A parrot is drawn around its feet:
``(0, 0)`` is where it grips the branch and the body extends upwards (negative y), about
84 px tall at scale 1.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from focuslab.ui.mascot.animation import Pose

HEAD_Y = -54.0  # eye line; emotes and bubbles are placed relative to the head
TOP_Y = -84.0  # top of the crest


@dataclass(frozen=True)
class Plumage:
    body: str
    outline: str
    wing: str
    belly: str
    beak: str = "#F59E2B"
    beak_outline: str = "#B5651A"


RED = Plumage("#E8483F", "#962A24", "#C9342C", "#F38A7F")
BLUE = Plumage("#3E72E6", "#1F3E8C", "#2C57BE", "#7FA4F2")
YELLOW = Plumage("#F8C935", "#A87A0C", "#E6A91F", "#FDE6A0", "#F0802A", "#A34F12")

INK = QColor("#20222B")
FOOT = QColor("#F2A33A")
CHEEK = QColor(255, 120, 150)


def _pen(color: QColor | str, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _body_path() -> QPainterPath:
    "A bean: narrower head on top of a round body."
    path = QPainterPath(QPointF(0, -80))
    path.cubicTo(19, -80, 29, -64, 29, -44)
    path.cubicTo(30, -16, 18, -3, 0, -3)
    path.cubicTo(-18, -3, -30, -16, -29, -44)
    path.cubicTo(-29, -64, -19, -80, 0, -80)
    return path


def _feather(length: float, width: float) -> QPainterPath:
    "A leaf shape pointing down from (0, 0)."
    path = QPainterPath(QPointF(0, 0))
    path.quadTo(width, length * 0.45, 0, length)
    path.quadTo(-width, length * 0.45, 0, 0)
    return path


BODY = _body_path()
WING = _feather(30, 9)
TUFT = _feather(-15, 4.5)


def paint_bird(p: QPainter, pose: Pose, plumage: Plumage, emblem: str | None = None) -> None:
    """Illustrated, layered parrot; all details follow the existing bone/pose animation."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(pose.x, pose.y)
    p.setOpacity(p.opacity() * pose.alpha)
    s = pose.scale * (1 + 0.1 * pose.puff)
    squash = max(0.5, pose.squash)
    p.scale(s / math.sqrt(squash), s * squash)

    # Tail appears behind the body; its outer feathers are in two different tones.
    for i, dx in enumerate((-1, 0, 1)):
        tail = QPainterPath(QPointF(dx * 7, -27))
        tail.cubicTo(QPointF(dx * 12 + 3, -10), QPointF(dx * 11 + 4, 0), QPointF(dx * 9, 3))
        tail.cubicTo(QPointF(dx * 6 - 1, -3), QPointF(dx * 4, -17), QPointF(dx * 7, -27))
        p.setPen(_pen(plumage.outline, 1.0))
        p.setBrush(QColor(plumage.wing if i != 1 else plumage.body))
        p.drawPath(tail)
    _feet(p, pose.airborne)
    p.rotate(pose.tilt)
    outline = _pen(plumage.outline, 2.0)

    # Crest is tied to the head transform, not the body, so looking around is natural.
    p.save()
    _face_transform(p, pose)
    p.setPen(outline)
    p.setBrush(QColor(plumage.body))
    for angle, length in ((-24, 0.8), (6, 1.0), (26, 0.58)):
        p.save()
        p.translate(0, -77.5)
        p.rotate(angle + pose.crest)
        p.scale(length, length)
        p.drawPath(TUFT)
        p.restore()
    p.restore()

    p.setPen(outline)
    p.setBrush(QColor(plumage.body))
    p.drawPath(BODY)

    # Transparent painted edges give the previously flat silhouette some volume.
    shade = QPainterPath(QPointF(17, -70))
    shade.cubicTo(34, -51, 29, -22, 17, -12)
    shade.cubicTo(13, -9, 9, -7, 4, -5)
    shade.cubicTo(26, -6, 32, -28, 28, -53)
    shade.cubicTo(27, -63, 23, -67, 17, -70)
    p.setPen(Qt.PenStyle.NoPen)
    c = QColor(plumage.outline)
    c.setAlpha(54)
    p.setBrush(c)
    p.drawPath(shade)
    glint = QPainterPath(QPointF(-22, -60))
    glint.cubicTo(-19, -69, -9, -75, -5, -74)
    glint.cubicTo(-14, -70, -19, -59, -20, -46)
    glint.cubicTo(-23, -47, -24, -54, -22, -60)
    p.setBrush(QColor(255, 255, 255, 43))
    p.drawPath(glint)

    belly = QLinearGradient(QPointF(-14, -37), QPointF(15, -7))
    lighter = QColor(plumage.belly).lighter(112)
    belly.setColorAt(0, lighter)
    belly.setColorAt(1, QColor(plumage.belly))
    p.setBrush(belly)
    p.drawEllipse(QPointF(0, -23), 17.5, 15.5)

    # The action sits on a medallion, with enough contrast to read at 100% scale.
    if emblem:
        p.setPen(_pen(QColor(255, 255, 255, 145), 0.9))
        p.setBrush(QColor(255, 250, 239, 192))
        p.drawEllipse(QPointF(0, -22), 10.6, 10.6)
        paint_icon(p, emblem, QPointF(0, -22), 7.8, on_belly=True)

    for side, angle in ((-1, pose.wing_l), (1, pose.wing_r)):
        p.save()
        p.translate(side * 24, -46)
        p.rotate(-side * angle - side * 8)
        p.setPen(_pen(plumage.outline, 1.6))
        p.setBrush(QColor(plumage.wing))
        p.drawPath(WING)
        p.setPen(_pen(QColor(255, 255, 255, 78), 1))
        feather_line = QPainterPath(QPointF(-side * 2, 5))
        feather_line.quadTo(QPointF(-side * 5.7, 14), QPointF(0, 24))
        p.drawPath(feather_line)
        p.setPen(_pen(QColor(plumage.outline), 1.1))
        p.drawLine(QPointF(side * 2, 20), QPointF(side * 5.2, 24))
        p.restore()

    p.save()
    _face_transform(p, pose)
    _face(p, pose, plumage)
    p.restore()
    p.restore()

def _face_transform(p: QPainter, pose: Pose) -> None:
    "Turning the head slides the face sideways a little and tilts it around the eye line."
    p.translate(pose.turn * 6, 0)
    p.translate(0, HEAD_Y)
    p.rotate(pose.head_tilt)
    p.translate(0, -HEAD_Y)


def _feet(p: QPainter, airborne: float) -> None:
    p.setPen(_pen(FOOT, 2.6))
    tuck = min(1.0, max(0.0, airborne))
    for side in (-1, 1):
        x = side * 8 * (1 - 0.3 * tuck)
        for dx in (-3, 0, 3):
            top = -5 - 4 * tuck
            p.drawLine(QPointF(x + dx * (1 - 0.5 * tuck), top), QPointF(x + dx, top + 7 - 4 * tuck))


def _face(p: QPainter, pose: Pose, plumage: Plumage) -> None:
    cheek = QColor(CHEEK)
    cheek.setAlpha(int(90 + 120 * min(1.0, pose.blush)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cheek)
    for side in (-1, 1):
        p.drawEllipse(QPointF(side * 17, -44), 4.3, 2.7)

    look = QPointF(pose.look_x * 2.2, pose.look_y * 1.6)
    for side in (-1, 1):
        _eye(p, QPointF(side * 10.5, HEAD_Y) + look, pose, side)

    # Beak: a hooked upper half and, when open, a lower half below a dark mouth.
    p.setPen(_pen(plumage.beak_outline, 1.5))
    if pose.beak_open > 0.05:
        p.setBrush(QColor("#7A2E2E"))
        p.drawEllipse(QPointF(0, -42.5 + 2 * pose.beak_open), 3.2, 2.6 * pose.beak_open + 0.5)
        lower = QPainterPath(QPointF(-3.6, -42 + 4 * pose.beak_open))
        lower.quadTo(0, -38 + 5 * pose.beak_open, 3.6, -42 + 4 * pose.beak_open)
        p.setBrush(QColor(plumage.beak))
        p.drawPath(lower)
    upper = QPainterPath(QPointF(-5.8, -48.5))
    upper.quadTo(0, -53, 5.8, -48.5)
    upper.quadTo(3.4, -41.5, 0, -39.5)
    upper.quadTo(-3.4, -41.5, -5.8, -48.5)
    p.setBrush(QColor(plumage.beak))
    p.drawPath(upper)


def _eye(p: QPainter, c: QPointF, pose: Pose, side: int) -> None:
    ink = _pen(INK, 2.2)
    if pose.eyes == "happy":
        path = QPainterPath(c + QPointF(-4, 1.5))
        path.quadTo(c + QPointF(0, -5), c + QPointF(4, 1.5))
        p.setPen(ink)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return
    open_ = min(1.0, max(0.0, pose.eye_open))
    if open_ < 0.3:
        path = QPainterPath(c + QPointF(-4, -0.5))
        path.quadTo(c + QPointF(0, 2.8), c + QPointF(4, -0.5))
        p.setPen(ink)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return

    r = 5.4 if pose.eyes == "wide" else 4.6
    p.setPen(Qt.PenStyle.NoPen)
    eye = QLinearGradient(c + QPointF(-3, -r), c + QPointF(2, r))
    eye.setColorAt(0, QColor("#141A2B"))
    eye.setColorAt(1, QColor("#32394B"))
    p.setBrush(eye)
    p.drawEllipse(c, r * 0.95, r * 1.1 * open_)
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(c + QPointF(1.4, -2.0 * open_), 1.65, 1.65 * open_)
    p.setBrush(QColor(222, 244, 255, 155))
    p.drawEllipse(c + QPointF(-1.8, 1.5 * open_), 0.7, 0.7 * open_)
    if pose.eyes == "angry":
        p.setPen(_pen(INK, 2.6))
        inner, outer = c + QPointF(-side * 4.5, -6), c + QPointF(side * 4.5, -9.5)
        p.drawLine(inner, outer)



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
