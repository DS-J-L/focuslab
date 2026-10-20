"""The opt-in flying interruption: after a long off-task run one parrot leaves the branch.

The flier swoops across the screen and hovers in front of your work saying "Focus!",
then returns. It is its own small always-on-top window: its opaque pixels cover what is
underneath (clicking the parrot shoos it home), while transparent pixels let clicks
through, and it never takes keyboard focus. It flies home at once when you are back on
task, pause, take a break, hide the overlay, or a monitor changes, and it does not fly
while a full-screen program (a game, a presentation) is in front.
"""

import math
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from focuslab.i18n import tr
from focuslab.ui.mascot.animation import Pose, ease_in_out, lerp
from focuslab.ui.mascot.renderer import HEAD_Y, Plumage, paint_bird, paint_emote

FLIGHT_FRAME_MS = 16  # smooth movement while flying (only during a sortie)
FLY_SCALE = 1.5  # the flier is drawn bigger than on the branch, to be noticed
SPEED = 650.0  # px/s along a swoop
HOVER_S = (2.4, 2.0, 2.0)  # hovering in front of your work at each waypoint
WIN_W, WIN_H = 280, 210
ANCHOR = QPointF(WIN_W / 2, WIN_H - 26)  # the flier's feet inside its window


@dataclass(frozen=True)
class Leg:
    p0: QPointF
    p1: QPointF
    p2: QPointF
    p3: QPointF
    duration: float
    hover: bool = False  # hovering at p0 (with the "Focus!" bubble)

    def point(self, u: float) -> QPointF:
        if self.hover:  # bobbing a whole number of times, so the path stays continuous
            bobs = max(1, round(self.duration * 0.8))
            return self.p0 + QPointF(0, 5 * math.sin(u * bobs * math.tau))
        u = ease_in_out(u)
        a, b = (1 - u), u
        return (
            self.p0 * a * a * a
            + self.p1 * 3 * a * a * b
            + self.p2 * 3 * a * b * b
            + self.p3 * b * b * b
        )


def swoop(start: QPointF, end: QPointF, rng: random.Random) -> Leg:
    "A curved flight from start to end, a little different every time."
    d = end - start
    length = math.hypot(d.x(), d.y()) or 1.0
    normal = QPointF(-d.y() / length, d.x() / length)
    bend = rng.uniform(-0.45, 0.45) * length
    p1 = start + d * 0.3 + normal * bend
    p2 = start + d * 0.7 + normal * bend * rng.uniform(0.2, 1.0)
    return Leg(start, p1, p2, end, max(0.8, min(2.4, length / SPEED)))


def plan_sortie(start: QPointF, area: QRectF, rng: random.Random) -> list[Leg]:
    """Out from the branch to three spots in the middle of the screen, hovering at each."""
    inner = area.adjusted(
        area.width() * 0.15, area.height() * 0.2, -area.width() * 0.15, -area.height() * 0.1
    )
    legs, here = [], start
    for hover in HOVER_S:
        for _ in range(12):  # far enough from the last spot to be a real swoop
            spot = QPointF(
                rng.uniform(inner.left(), inner.right()), rng.uniform(inner.top(), inner.bottom())
            )
            if math.hypot(spot.x() - here.x(), spot.y() - here.y()) > min(240, area.width() / 4):
                break
        legs.append(swoop(here, spot, rng))
        legs.append(Leg(spot, spot, spot, spot, hover, hover=True))
        here = spot
    return legs


def foreground_is_fullscreen() -> bool:
    "Whether the window in front covers its whole monitor (a game, video or slideshow)."
    if sys.platform != "win32":
        return False
    try:
        import win32api
        import win32gui

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False  # the desktop and taskbar are not programs
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Monitor"]
        return (left, top, right, bottom) == tuple(monitor)
    except Exception:  # noqa: BLE001 - never let a probe failure start or stop a flight
        return False


class FlightWindow(QWidget):
    """The flying parrot. Clicking it shoos it home."""

    shooed = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setWindowTitle("FocusLab")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(WIN_W, WIN_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Click to send the parrot back"))
        self.plumage: Plumage | None = None
        self.pose = Pose()
        self.bubble = False
        self.facing = 1  # the bubble goes on the side the parrot is not flying to

    def place(self, feet: QPointF) -> None:
        self.move((feet - ANCHOR).toPoint())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.shooed.emit()

    def paintEvent(self, event) -> None:
        if self.plumage is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(ANCHOR)
        paint_bird(p, self.pose, self.plumage)
        p.resetTransform()
        head = ANCHOR + QPointF(self.pose.x, self.pose.y + HEAD_Y * self.pose.scale)
        if self.pose.emote:  # drawn at the flier's size, so it clears its head
            p.save()
            p.translate(head)
            p.scale(self.pose.scale, self.pose.scale)
            paint_emote(p, self.pose.emote, QPointF(0, 0), self.pose.emote_t)
            p.restore()
        if self.bubble:
            _shout(p, head + QPointF(-self.facing * 92, -56), tr("Focus!"))
        p.end()


def _shout(p: QPainter, c: QPointF, text: str) -> None:
    "A spiky white shout bubble."
    font = QFont()
    font.setPixelSize(17)
    font.setBold(True)
    p.setFont(font)
    width = max(70, p.fontMetrics().horizontalAdvance(text) + 26)
    path = QPainterPath()
    spikes = 14
    for i in range(spikes * 2 + 1):
        angle = math.tau * i / (spikes * 2)
        r = 1.0 if i % 2 == 0 else 0.82
        point = c + QPointF(math.cos(angle) * width / 2 * r, math.sin(angle) * 24 * r)
        path.lineTo(point) if i else path.moveTo(point)
    p.setPen(QPen(QColor("#20222B"), 2))
    p.setBrush(QColor("white"))
    p.drawPath(path)
    p.setPen(QColor("#20222B"))
    p.drawText(QRectF(c.x() - width / 2, c.y() - 14, width, 28), Qt.AlignmentFlag.AlignCenter, text)


class FlightController(QObject):
    """Decides when one parrot flies, flies it, and brings it home.

    ``home`` returns where the flier's seat is on screen right now (the overlay can move);
    ``area`` the screen to fly over. ``departed``/``landed`` carry the parrot's index.
    """

    departed = Signal(int)
    landed = Signal(int)

    def __init__(
        self,
        clock: Callable[[], float],
        home: Callable[[int], QPointF],
        area: Callable[[], QRectF],
        plumage: Callable[[int], Plumage],
        perched_scale: float = 1.0,
        rng: random.Random | None = None,
        fullscreen: Callable[[], bool] = foreground_is_fullscreen,
    ) -> None:
        super().__init__()
        self.clock, self.home, self.area, self.plumage = clock, home, area, plumage
        self.perched_scale = perched_scale  # leaves and lands at its size on the branch
        self.fullscreen = fullscreen
        self.rng = rng or random.Random()
        self.enabled = False
        self.interval_s = 300.0
        self.window = FlightWindow()
        self.window.shooed.connect(self.recall)
        self._timer = QTimer(self, interval=FLIGHT_FRAME_MS)
        self._timer.timeout.connect(self._frame)
        self.flier: int | None = None
        self.returning = False
        self._legs: list[Leg] = []
        self._leg_start = 0.0
        self._last_departure: float | None = None
        self._next_flier = 0
        self._shooed_at: float | None = None

    @property
    def flying(self) -> bool:
        return self.flier is not None

    def consider(self, alarmed: bool, allowed: bool) -> None:
        """Called on every poll. ``alarmed``: off task long enough; ``allowed``: the overlay
        is shown and the session running."""
        now = self.clock()
        if self.flying:
            if not (alarmed and allowed and self.enabled):
                self.recall() if allowed else self.abort()
            return
        if not (alarmed and allowed and self.enabled):
            return
        if self._last_departure is not None and now - self._last_departure < self.interval_s:
            return
        if self.fullscreen():
            return
        self.depart(now)

    def depart(self, now: float) -> None:
        self.flier = self._next_flier
        self._next_flier = (self._next_flier + 1) % 3
        self._last_departure = now
        self.returning = False
        self._shooed_at = None
        start = self.home(self.flier)
        self._legs = plan_sortie(start, self.area(), self.rng)
        self._leg_start = now
        self.window.plumage = self.plumage(self.flier)
        self._frame()
        self.window.show()
        self.window.raise_()
        self._timer.start()
        self.departed.emit(self.flier)

    def recall(self) -> None:
        "Fly home now (back on task, paused, on a break, or shooed)."
        if not self.flying or self.returning:
            return
        now = self.clock()
        if self.sender() is self.window:
            self._shooed_at = now
        here = self._position(now)
        self.returning = True
        self._legs = [swoop(here, self.home(self.flier), self.rng)]
        self._leg_start = now
        self._frame()

    def abort(self) -> None:
        "Vanish at once (overlay hidden, session over, screen gone)."
        if not self.flying:
            return
        self._timer.stop()
        self.window.hide()
        index, self.flier = self.flier, None
        self.landed.emit(index)

    def _position(self, now: float) -> QPointF:
        t = now - self._leg_start
        for leg in self._legs:
            if t <= leg.duration:
                return leg.point(t / leg.duration)
            t -= leg.duration
        return self._legs[-1].point(1.0)

    def _frame(self) -> None:
        now = self.clock()
        t = now - self._leg_start
        index, leg = 0, self._legs[0]
        for index, leg in enumerate(self._legs):  # noqa: B007 - the current leg is kept
            if t <= leg.duration:
                break
            t -= leg.duration
        else:
            if self.returning:
                self._timer.stop()
                self.window.hide()
                index, self.flier = self.flier, None
                self.landed.emit(index)
                return
            self.recall()  # the outing is over: home
            return
        u = min(1.0, t / leg.duration)
        here = leg.point(u)
        ahead = leg.point(min(1.0, u + 0.02))
        dx = ahead.x() - here.x()
        if abs(dx) > 0.3:
            self.window.facing = 1 if dx > 0 else -1
        first = index == 0 and not self.returning
        grow = ease_in_out(u) if first else 1.0
        if self.returning:
            grow = 1.0 - ease_in_out(max(0.0, (u - 0.5) * 2))  # shrink while landing
        flap = 55 + 45 * math.sin(now * math.tau * (3.0 if leg.hover else 5.0))
        shooed = self._shooed_at is not None and now - self._shooed_at < 1.2
        self.window.pose = replace(
            Pose(),
            scale=lerp(self.perched_scale, FLY_SCALE, grow),
            tilt=max(-25.0, min(25.0, dx * 1.5)) if not leg.hover else 0.0,
            airborne=lerp(0.0, 1.0, grow) if (first or self.returning) else 1.0,
            wing_l=flap,
            wing_r=flap,
            eyes="wide" if shooed else "angry",
            puff=0.6,
            look_y=0.4,
            emote="alert" if shooed else "anger",
            emote_t=now,
        )
        self.window.bubble = leg.hover and not self.returning
        self.window.place(here)
        self.window.update()


def screen_area(widget: QWidget) -> QRectF:
    screen = widget.screen() or QGuiApplication.primaryScreen()
    return QRectF(screen.availableGeometry())
