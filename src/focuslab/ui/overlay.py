"""Floating session overlay: three parrots on a branch above the session time.

The parrots are the controls: red pauses or resumes, blue ends the session and yellow
starts or ends a break. Minimize and close sit in the top-right corner; minimized, the
overlay is just a small parrot and the time. If the user opted in, one parrot leaves the
branch to fly around the screen after a long off-task run (``mascot.flight_overlay``).
"""

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QGuiApplication,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focuslab.domain.models import FocusState
from focuslab.i18n import tr
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.context import AppContext
from focuslab.ui.mascot.animation import Pose
from focuslab.ui.mascot.artwork import character_art, preload_artwork
from focuslab.ui.mascot.behavior_policy import BehaviorPolicy, Mood
from focuslab.ui.mascot.director import BREAK, FINISH, PAUSE, WINDOW, Director
from focuslab.ui.mascot.flight_overlay import FlightController, screen_area
from focuslab.ui.mascot.petting import PettingGesture
from focuslab.ui.mascot.renderer import (
    HEAD_Y,
    RED,
    character_top,
    paint_bird,
    paint_branch,
    paint_bubble,
    paint_emote,
    paint_plaque,
)
from focuslab.ui.mascot.studio import (
    paint_progress,
    paint_scene,
    paint_seat,
    paint_status_light,
)
from focuslab.ui.theme import set_style_flag
from focuslab.ui.widgets import clock_text, timer_text

MARGIN = 16
POS_KEY = "ui.overlay_pos"  # top-right corner, so collapsing keeps the right edge in place
FRAME_MS = 16  # target ~60 Hz during gestures and the complete blink
RESTING_FRAME_MS = 33  # gentle breathing; a due blink wakes the faster timer

# Scene geometry (px) of the expanded overlay.
SCENE_W, SCENE_H = 360, 288
SEATS = (76.0, 180.0, 284.0)  # x of each parrot's feet
BRANCH = QRectF(14, 198, 332, 14)
SEAT_Y = BRANCH.top() + 3
PLAQUE = QRectF(54, 235, 252, 38)
STRINGS = (112.0, 248.0)
BIRD_SCALE = 1.08


def status_texts() -> tuple[str, str, str]:
    return tr("Focusing"), tr("Session paused"), tr("On a break")


def session_seconds(snap: LiveSnapshot) -> int:
    """Session time without pauses and breaks. Unrelated to the estimated focus state."""
    return max(0, snap.active_s - snap.seconds.get(FocusState.BREAK, 0))


def long_text(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    h, m = divmod(m, 60)
    if h:
        return tr("{p0}h {p1}m {p2}s", p0=h, p1=m, p2=s)
    return tr("{p0}m {p1}s", p0=m, p1=s)


def _mascot() -> QLabel:
    label = QLabel()
    ratio = QGuiApplication.primaryScreen().devicePixelRatio()
    pixmap = QPixmap(round(34 * ratio), round(34 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.translate(17, 32)
    painter.scale(0.29, 0.29)
    paint_bird(painter, Pose(), RED)
    painter.end()
    label.setPixmap(pixmap)
    return label


class ParrotButton(QAbstractButton):
    """An invisible click target over one parrot; the scene draws the parrot itself."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.icon_name = ""  # shown in the speech bubble while hovered
        self.emblem = ""  # worn on the parrot's necklace pendant
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleDescription(tr(
            "Move the pointer up and down over the head to pet this parrot. No click needed."
        ))

    def paintEvent(self, event: QPaintEvent) -> None:
        pass


class PerchView(QWidget):
    """The expanded overlay: parrots on a branch, the time plaque, and window buttons."""

    def __init__(self, parent: QWidget | None = None, clock=time.monotonic) -> None:
        super().__init__(parent)
        preload_artwork()
        self.setFixedSize(SCENE_W, SCENE_H)
        self.clock = clock
        self.director = Director()
        self.setMouseTracking(True)
        self._pet_gesture = PettingGesture()
        self._pet_target: int | None = None
        self._pet_zones = []
        for actor in self.director.actors:
            zone = QPainterPath()
            zone.setFillRule(Qt.FillRule.WindingFill)  # crest/head overlap is still pettable
            zone.addEllipse(QRectF(-35, -110, 70, 68))
            crest = character_art(actor.plumage.character_id).crest
            if crest is not None:
                zone.addRect(crest.adjusted(-3, -3, 3, 3))
            self._pet_zones.append(zone)
        self.visual_state = "focusing"
        self.progress_fraction: float | None = None

        self.status = QLabel(self, objectName="OverlayStatus")
        self.status.setGeometry(29, 8, 128, 23)
        self.collapse_button = QPushButton("−", self)
        self.collapse_button.setToolTip(tr("Collapse"))
        self.close_button = QPushButton("×", self)
        self.close_button.setToolTip(tr("Hide the overlay. The session continues."))
        for i, button in enumerate((self.collapse_button, self.close_button)):
            button.setGeometry(SCENE_W - 62 + i * 29, 6, 26, 24)
            button.installEventFilter(self)

        self.parrots = tuple(ParrotButton(self) for _ in SEATS)
        for seat, button in zip(SEATS, self.parrots, strict=True):
            button.setGeometry(int(seat - 48), 43, 96, 176)
            button.installEventFilter(self)
        self.time = QLabel(self, objectName="OverlayTime", alignment=Qt.AlignmentFlag.AlignCenter)
        self.time.setGeometry(PLAQUE.adjusted(5, 0, -5, -5).toRect())
        self.time.setToolTip(tr("Session time without pauses and breaks, not estimated focus"))

        self._timer = QTimer(self, interval=FRAME_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self.update)
        self._backdrop: QPixmap | None = None

    @property
    def animating(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, event: QShowEvent) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self._timer.stop()
        self._reset_pet()
        self.director.set_hover(None, self.clock())
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if watched in self.parrots:
            if kind == QEvent.Type.MouseMove:
                self._track_pet(event.position() + QPointF(watched.pos()), event.buttons())
            elif kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                self._reset_pet()
            elif kind == QEvent.Type.Leave and self._pet_target == self.parrots.index(watched):
                self._reset_pet()
        if kind in (QEvent.Type.Enter, QEvent.Type.Leave):
            entered = kind is QEvent.Type.Enter
            if watched in self.parrots:
                index = self.parrots.index(watched)
                target = index if entered and watched.isEnabled() else None
            else:
                target = WINDOW if entered else None
            self.director.set_hover(target, self.clock())
        return False

    def _reset_pet(self) -> None:
        self._pet_target = None
        self._pet_gesture.reset()
        for button in self.parrots:
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def _track_pet(self, point: QPointF, buttons: Qt.MouseButton) -> None:
        if buttons != Qt.MouseButton.NoButton or not self.isVisible():
            self._reset_pet()
            return
        target = next((i for i, zone in enumerate(self._pet_zones)
                       if i not in self.director.away and zone.contains(
                           (point - QPointF(SEATS[i], SEAT_Y)) / BIRD_SCALE)), None)
        if target != self._pet_target:
            self._reset_pet()
            self._pet_target = target
        if target is None:
            return
        self.parrots[target].setCursor(Qt.CursorShape.OpenHandCursor)
        if self._pet_gesture.move(point.x(), point.y(), self.clock()):
            self.director.pet(target, self.clock())
            self._timer.setInterval(FRAME_MS)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Disabled action buttons (yellow during a pause) may propagate moves here;
        # the bird can still enjoy petting while its necklace action is unavailable.
        self._track_pet(event.position(), event.buttons())
        super().mouseMoveEvent(event)

    def _background(self) -> QPixmap:
        "The branch and plaque never move: paint them once per display scale."
        ratio = self.devicePixelRatioF()
        if self._backdrop is None or self._backdrop.devicePixelRatio() != ratio:
            pixmap = QPixmap(self.size() * ratio)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(QColor(0, 0, 0, 0))
            p = QPainter(pixmap)
            paint_scene(p, SCENE_W, SCENE_H)
            paint_plaque(p, PLAQUE, STRINGS, BRANCH.bottom())
            paint_branch(p, BRANCH)
            p.end()
            self._backdrop = pixmap
        return self._backdrop

    def paintEvent(self, event: QPaintEvent) -> None:
        poses = self.director.poses(self.clock())
        interval = RESTING_FRAME_MS if self.director.resting else FRAME_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._background())
        paint_status_light(p, self.visual_state)
        paint_progress(p, PLAQUE, self.progress_fraction, self.visual_state)
        for seat, pose, actor, button in zip(
            SEATS, poses, self.director.actors, self.parrots, strict=True
        ):
            if pose.alpha > 0:
                paint_seat(
                    p, seat, SEAT_Y,
                    self.director.hover == self.parrots.index(button),
                    button.isEnabled(),
                )
            p.save()
            p.translate(seat, SEAT_Y)
            p.scale(BIRD_SCALE, BIRD_SCALE)
            paint_bird(
                p, pose, actor.plumage, button.emblem,
                enabled=button.isEnabled(), focused=button.hasFocus(),
                hovered=self.director.hover == self.parrots.index(button),
            )
            p.restore()
        # Symbols and bubbles last, so a neighbour never covers them.
        for seat, pose in zip(SEATS, poses, strict=True):
            if pose.emote:
                paint_emote(p, pose.emote, scene_point(seat, pose, HEAD_Y), pose.emote_t)
        hovered = self.director.hover
        if (isinstance(hovered, int) and self.parrots[hovered].icon_name
                and not self.director.actors[hovered].content(self.clock())):
            top = character_top(self.director.actors[hovered].plumage)
            tip = scene_point(SEATS[hovered], poses[hovered], top) + QPointF(4, 0)
            tip.setY(max(84, tip.y()))  # keep the hint below the status/header controls
            paint_bubble(p, tip, self.parrots[hovered].icon_name)
        p.end()


def scene_point(seat: float, pose: Pose, height: float) -> QPointF:
    "Where a point ``height`` px above a parrot's feet (at scale 1) is in the scene."
    lift = height * pose.scale * pose.squash
    return QPointF(seat + pose.x * BIRD_SCALE, SEAT_Y + (pose.y + lift) * BIRD_SCALE)


class SessionOverlay(QWidget):
    pauseRequested = Signal()
    finishRequested = Signal()
    breakRequested = Signal()

    def __init__(self, ctx: AppContext) -> None:
        # No parent: a window owned by the main window would vanish when it is minimized.
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.ctx = ctx
        self.setWindowTitle("FocusLab")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._press: QPoint | None = None  # global press position while the button is held
        self._grab = QPoint()
        self._dragged = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        panel = QFrame(objectName="Overlay")
        outer.addWidget(panel)
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        self.full = PerchView()
        self.perch = self.full
        self.status = self.full.status
        self.time = self.full.time
        self.collapse_button = self.full.collapse_button
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(True))
        self.close_button = self.full.close_button
        self.close_button.clicked.connect(self.hide)
        self.pause_button, self.finish_button, self.break_button = (
            self.full.parrots[i] for i in (PAUSE, FINISH, BREAK)
        )
        self.pause_button.clicked.connect(self.pauseRequested)
        self.finish_button.clicked.connect(self.finishRequested)
        self.break_button.clicked.connect(self.breakRequested)
        self.finish_button.setText(tr("End"))
        self.finish_button.setToolTip(tr("End"))
        self.finish_button.icon_name = self.finish_button.emblem = "stop"
        box.addWidget(self.full)

        self.mini = QWidget()
        mini = QHBoxLayout(self.mini)
        mini.setContentsMargins(12, 8, 12, 8)
        mini.setSpacing(6)
        mini.addWidget(_mascot())
        self.mini_time = QLabel()
        mini.addWidget(self.mini_time)
        self.mini.setToolTip(tr("Click to expand"))
        self.mini.hide()
        box.addWidget(self.mini)
        self.policy = BehaviorPolicy()
        director = self.perch.director
        self.flight = FlightController(
            clock=lambda: self.perch.clock(),
            home=self._seat_on_screen,
            area=lambda: screen_area(self),
            plumage=lambda i: director.actors[i].plumage,
            perched_scale=BIRD_SCALE,
        )
        self.flight.departed.connect(lambda i: self._set_away(i, True))
        self.flight.landed.connect(lambda i: self._set_away(i, False))
        app = QGuiApplication.instance()
        if app is not None:  # a monitor coming or going: the flight path is stale
            app.screenRemoved.connect(lambda *_: self.flight.abort())
            app.screenAdded.connect(lambda *_: self.flight.abort())
        self.apply_settings()

    def apply_settings(self) -> None:
        self.perch.director.set_motion(self.ctx.mascot_motion)
        self.policy.reactions = self.ctx.mascot_reactions
        self.policy.alarm_after = float(self.ctx.flight_after_s)
        self.flight.enabled = self.ctx.flight_enabled
        self.flight.interval_s = self.ctx.flight_interval_min * 60.0

    # flying -------------------------------------------------------------------------
    def _seat_on_screen(self, i: int) -> QPointF:
        "Where parrot ``i`` sits, in global coordinates (the time pill when collapsed)."
        if self.collapsed:
            return QPointF(self.mini.mapToGlobal(self.mini.rect().center()))
        return QPointF(self.perch.mapToGlobal(QPoint(int(SEATS[i]), int(SEAT_Y))))

    def _set_away(self, i: int, away: bool) -> None:
        director = self.perch.director
        if away and director.hover == i:  # no bubble over an empty seat
            director.set_hover(None, self.perch.clock())
        director.set_away(i, away, self.perch.clock())
        self.perch.parrots[i].setVisible(not away)  # no button on an empty seat

    def hideEvent(self, event: QHideEvent) -> None:
        self.flight.abort()  # hidden by the user or the session ended: no flying either
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.flight.abort()
        self.flight.window.close()
        super().closeEvent(event)

    # showing ------------------------------------------------------------------------
    def start(self, snap: LiveSnapshot) -> None:
        """Show expanded at the remembered position (or the top-right of the screen)."""
        self.refresh(snap)
        if snap.lifecycle not in ACTIVE:
            return
        self.set_collapsed(False)
        right, top = self._saved_corner()
        self.move(right - self.width(), top)
        self.show()

    def _saved_corner(self) -> tuple[int, int]:
        try:
            right, top = (int(v) for v in (self.ctx.setting(POS_KEY) or "").split(","))
            # Never restore off-screen, for example after a monitor was unplugged.
            if QGuiApplication.screenAt(QPoint(right - 1, top)) is not None:
                return right, top
        except ValueError:
            pass
        geo = QGuiApplication.primaryScreen().availableGeometry()
        return geo.x() + geo.width() - MARGIN, geo.y() + MARGIN

    def set_collapsed(self, on: bool) -> None:
        self.full.setVisible(not on)
        self.mini.setVisible(on)
        self.layout().activate()  # resize now rather than on the next event loop pass

    def resizeEvent(self, event: QResizeEvent) -> None:
        # Grow and shrink to the left: the overlay sits at the right edge of the screen.
        old = event.oldSize()
        if self.isVisible() and old.isValid():
            self.move(self.x() + old.width() - self.width(), self.y())
        super().resizeEvent(event)

    @property
    def collapsed(self) -> bool:
        return self.mini.isVisibleTo(self)

    def refresh(self, snap: LiveSnapshot) -> None:
        if snap.lifecycle not in ACTIVE:
            self.hide()
            return
        now = self.perch.clock()
        mood = self.policy.update(snap, now)
        self.perch.director.set_mood(mood, now)
        content = any(actor.content(now) for actor in self.perch.director.actors)
        self.flight.consider(mood is Mood.ALARM and not content, self.isVisible())
        paused = snap.lifecycle is Lifecycle.PAUSED
        focusing, paused_text, break_text = status_texts()
        self.status.setText(paused_text if paused else break_text if snap.on_break else focusing)
        self.perch.visual_state = "paused" if paused else "break" if snap.on_break else "focusing"
        pause_text = tr("Resume") if paused else tr("Pause")
        self.pause_button.setText(pause_text)
        self.pause_button.setToolTip(pause_text)
        self.pause_button.icon_name = self.pause_button.emblem = "play" if paused else "pause"
        break_text = tr("End break") if snap.on_break else tr("Start break")
        self.break_button.setText(break_text)
        self.break_button.setToolTip(break_text)
        self.break_button.icon_name = "back" if snap.on_break else "cup"
        self.break_button.emblem = "cup"
        self.break_button.setEnabled(snap.lifecycle is Lifecycle.RUNNING)
        planned = snap.config.planned_minutes * 60 if snap.config else 0
        self.perch.progress_fraction = (
            min(1.0, snap.active_s / planned) if planned > 0 else None
        )
        if self.ctx.timer_countdown and planned:  # time left to the target, then overtime
            left = planned - snap.active_s
            self.time.setText(
                tr("{p0} left", p0=long_text(left))
                if left >= 0
                else tr("{p0} over", p0=long_text(-left))
            )
            self.mini_time.setText(timer_text(snap.active_s, planned, True))
            tip = tr("Time left to the target time")
        else:
            seconds = session_seconds(snap)
            self.time.setText(long_text(seconds))
            self.mini_time.setText(clock_text(seconds))
            tip = tr("Session time without pauses and breaks, not estimated focus")
        if self.time.toolTip() != tip:
            self.time.setToolTip(tip)
        for label in (self.mini_time, self.time):  # a stopped clock is greyed out
            set_style_flag(label, "paused", paused)  # restyles only on a change
        self.perch.update()

    # dragging -----------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._grab = self._press - self.pos()
            self._dragged = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None:
            return
        point = event.globalPosition().toPoint()
        if (point - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._dragged = True
        if self._dragged:
            self.move(point - self._grab)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._press = None
        if self._dragged:
            self.ctx.set_setting(POS_KEY, f"{self.x() + self.width()},{self.y()}")
        elif self.collapsed:
            self.set_collapsed(False)
