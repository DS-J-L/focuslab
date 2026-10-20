"Floating session overlay: session time on top of other programs, with pause and end."

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
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
from focuslab.ui.widgets import clock_text

MARGIN = 16
POS_KEY = "ui.overlay_pos"  # top-right corner, so collapsing keeps the right edge in place

STYLE = """
#Overlay { background: rgba(31, 36, 48, 238); border-radius: 12px; }
#Overlay QLabel { color: white; background: transparent; }
#Overlay QLabel#OverlayStatus { color: #C9CED8; font-size: 12px; }
#Overlay QLabel#OverlayTime { font-size: 22px; font-weight: 700; }
#Overlay QPushButton { background: transparent; border: none; border-radius: 6px;
                       color: #C9CED8; padding: 2px 6px; min-height: 0; }
#Overlay QPushButton:hover { color: white; background: #343F60; }
"""


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
    pixmap = QPixmap(str(Path(__file__).with_name("icons") / "parrot-telescope.png"))
    label.setPixmap(
        pixmap.scaled(
            18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    )
    return label


class SessionOverlay(QWidget):
    pauseRequested = Signal()
    finishRequested = Signal()

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
        self.setStyleSheet(STYLE)
        self._press: QPoint | None = None  # global press position while the button is held
        self._grab = QPoint()
        self._dragged = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        panel = QFrame(objectName="Overlay")
        outer.addWidget(panel)
        box = QVBoxLayout(panel)
        box.setContentsMargins(12, 6, 6, 8)
        box.setSpacing(0)

        self.full = QWidget()
        full = QVBoxLayout(self.full)
        full.setContentsMargins(0, 0, 0, 0)
        full.setSpacing(2)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(_mascot())
        self.status = QLabel(objectName="OverlayStatus")
        header.addWidget(self.status)
        header.addStretch()
        self.collapse_button = QPushButton("─")
        self.collapse_button.setToolTip(tr("Collapse"))
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(True))
        self.close_button = QPushButton("×")
        self.close_button.setToolTip(tr("Hide the overlay. The session continues."))
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.collapse_button)
        header.addWidget(self.close_button)
        full.addLayout(header)
        self.time = QLabel(objectName="OverlayTime")
        self.time.setToolTip(tr("Session time without pauses and breaks, not estimated focus"))
        full.addWidget(self.time)
        controls = QHBoxLayout()
        controls.setSpacing(0)
        self.pause_button = QPushButton()
        self.pause_button.clicked.connect(self.pauseRequested)
        self.finish_button = QPushButton(tr("End"))
        self.finish_button.clicked.connect(self.finishRequested)
        controls.addWidget(self.pause_button)
        controls.addWidget(QLabel("·"))
        controls.addWidget(self.finish_button)
        controls.addStretch()
        full.addLayout(controls)
        box.addWidget(self.full)

        self.mini = QWidget()
        mini = QHBoxLayout(self.mini)
        mini.setContentsMargins(0, 2, 6, 0)
        mini.setSpacing(6)
        mini.addWidget(_mascot())
        self.mini_time = QLabel()
        mini.addWidget(self.mini_time)
        self.mini.setToolTip(tr("Click to expand"))
        self.mini.hide()
        box.addWidget(self.mini)

        # Wide enough for every state, so the panel never changes width while it is shown.
        self.status.ensurePolished()  # measure with the stylesheet font
        self.status.setMinimumWidth(
            max(self.status.fontMetrics().horizontalAdvance(text) for text in status_texts())
        )

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
        paused = snap.lifecycle is Lifecycle.PAUSED
        focusing, paused_text, break_text = status_texts()
        self.status.setText(paused_text if paused else break_text if snap.on_break else focusing)
        self.pause_button.setText(tr("Resume") if paused else tr("Pause"))
        seconds = session_seconds(snap)
        self.time.setText(long_text(seconds))
        self.mini_time.setText(clock_text(seconds))
        style = "color: #8C94A6;" if paused else ""  # a stopped clock is greyed out
        if self.mini_time.styleSheet() != style:  # restyling on every poll would re-polish
            self.mini_time.setStyleSheet(style)

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
