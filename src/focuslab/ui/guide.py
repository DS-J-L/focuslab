"""A short tour for first-time users, shown once after first-run setup.

Each step dims the window except the place it talks about (a menu row, the (+), a Settings
section) and explains it in a bubble beside it. Every step can be skipped, and Settings >
Appearance opens it again. It only explains; it changes no setting and collects nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from focuslab.i18n import tr
from focuslab.ui.theme import colors

BUBBLE_WIDTH = 340
GAP = 14  # between the highlighted place and the bubble
EDGE = 12  # the bubble keeps this far from the window edges
HOLE_PADDING = 6
RADIUS = 10
DIM = QColor(0, 0, 0, 150)


@dataclass(frozen=True)
class GuideStep:
    title: str
    text: str
    target: str | None  # the place the step points at, resolved by the main window


def guide_steps() -> list[GuideStep]:
    "Every step, in the current language."
    return [
        GuideStep(
            tr("A quick tour of FocusLab"),
            tr(
                "A one-minute tour that points at where each thing is. You can skip it now "
                "and open it again from Settings > Appearance."
            ),
            None,
        ),
        GuideStep(
            tr("Home"),
            tr(
                "Home shows today's totals: the top row comes from automatic recording, the "
                "bottom row from the focus sessions you start. Your recent sessions are below."
            ),
            "home",
        ),
        GuideStep(
            tr("Activity"),
            tr(
                "With automatic recording on, Activity shows which programs and sites you "
                "used, as a timeline you can correct."
            ),
            "activity",
        ),
        GuideStep(
            tr("Start a focus session"),
            tr(
                "Press this round + to start. Write a goal, choose a work mode and a target "
                "time, and check the allowed apps. The camera is optional and stays off unless "
                "you turn it on."
            ),
            "new_session",
        ),
        GuideStep(
            tr("Work modes"),
            tr(
                "A work mode decides what counts as normal work, for example whether looking "
                "down at paper is work. Add your own modes with their own allowed apps here."
            ),
            "work_modes",
        ),
        GuideStep(
            tr("Recording and privacy"),
            tr(
                "Turn automatic recording off or pause it here. Below are the camera, how long "
                "records are kept, export and delete. Records stay on this PC."
            ),
            "recording",
        ),
        GuideStep(
            tr("During and after a session"),
            tr(
                "The parrots on the overlay pause, end, or start a break. Reports show each "
                "session afterwards, and you can correct any estimate. Estimates describe "
                "observable behavior; they are not measurements of attention."
            ),
            "reports",
        ),
        GuideStep(
            tr("Open this tour again"),
            tr("That's all. This button shows the tour again whenever you need it."),
            "guide",
        ),
    ]


class GuideTour(QWidget):
    """Covers `parent` and steps through `steps`. `locate` brings a step's place on screen (it
    may switch pages or scroll) and returns its global rectangle, or None to center the bubble.
    Back / Next move; Skip or Esc ends early. It deletes itself when closed."""

    finished = Signal(bool)  # True when the last step was reached and closed with Get started

    def __init__(
        self,
        parent: QWidget,
        steps: list[GuideStep],
        locate: Callable[[str | None], QRect | None],
    ) -> None:
        super().__init__(parent)
        self._steps = steps
        self._locate = locate
        self._hole = QRect()  # in this widget's coordinates; empty when nothing is pointed at
        self.step = 0
        self.setAccessibleName(tr("FocusLab guide"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.bubble = QWidget(self)
        self.bubble.setFixedWidth(BUBBLE_WIDTH)
        layout = QVBoxLayout(self.bubble)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(8)
        self.counter = QLabel(objectName="Muted")
        layout.addWidget(self.counter)
        self.title = QLabel(objectName="PopoverTitle", wordWrap=True)
        layout.addWidget(self.title)
        self.text = QLabel(wordWrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.text)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip = QPushButton(tr("Skip guide"))
        self.skip.clicked.connect(lambda: self.close_tour(False))
        self.back = QPushButton(tr("Back"))
        self.back.clicked.connect(lambda: self.show_step(self.step - 1))
        self.next = QPushButton(objectName="Primary")
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.skip)
        buttons.addStretch()
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        parent.installEventFilter(self)

    @property
    def last(self) -> bool:
        return self.step == len(self._steps) - 1

    def start(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = max(0, min(step, len(self._steps) - 1))
        current = self._steps[self.step]
        self.counter.setText(tr("Step {p0} of {p1}", p0=self.step + 1, p1=len(self._steps)))
        self.title.setText(current.title)
        self.text.setText(current.text)
        self.back.setEnabled(self.step > 0)
        self.skip.setVisible(not self.last)
        self.next.setText(tr("Get started") if self.last else tr("Next"))
        self.next.setFocus()
        self._place()
        # A page switch or a scroll settles after this event; place again once it has.
        QTimer.singleShot(0, self, self._place)

    def _next(self) -> None:
        if self.last:
            self.close_tour(True)
        else:
            self.show_step(self.step + 1)

    def close_tour(self, completed: bool) -> None:
        self.parentWidget().removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    # geometry and painting ------------------------------------------------------------------
    def _place(self) -> None:
        if not self.isVisible():
            return
        target = self._locate(self._steps[self.step].target)
        if target is None or target.isEmpty():
            self._hole = QRect()
        else:
            hole = QRect(self.mapFromGlobal(target.topLeft()), target.size())
            pad = HOLE_PADDING
            self._hole = hole.adjusted(-pad, -pad, pad, pad).intersected(self.rect())
        self.bubble.adjustSize()
        self.bubble.move(self._bubble_position(self.bubble.size()))
        self.update()

    def _bubble_position(self, size) -> QPoint:
        "Beside the hole: right, left, below, then above, whichever fits; centered without one."
        area = self.rect().adjusted(EDGE, EDGE, -EDGE, -EDGE)
        hole = self._hole
        w, h = size.width(), size.height()
        if hole.isEmpty():
            return area.center() - QPoint(w // 2, h // 2)
        middle_y = hole.center().y() - h // 2
        middle_x = hole.center().x() - w // 2
        candidates = (
            QPoint(hole.right() + GAP, middle_y),
            QPoint(hole.left() - GAP - w, middle_y),
            QPoint(middle_x, hole.bottom() + GAP),
            QPoint(middle_x, hole.top() - GAP - h),
        )

        def clamp(p: QPoint) -> QPoint:
            x = min(max(p.x(), area.left()), area.right() - w)
            y = min(max(p.y(), area.top()), area.bottom() - h)
            return QPoint(x, y)

        for point in candidates:
            placed = clamp(point)
            if not QRect(placed, size).intersects(hole):
                return placed
        return clamp(QPoint(area.right() - w, area.bottom() - h))  # a huge hole: a corner

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = colors()
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if not self._hole.isEmpty():
            w, h = self._hole.width(), self._hole.height()
            radius = min(w, h) / 2 if abs(w - h) < 8 else RADIUS  # a ring around the round (+)
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._hole), radius, radius)
            dim = dim.subtracted(hole)
            painter.fillPath(dim, DIM)
            painter.strokePath(hole, QPen(QColor(palette.accent_text), 2))
        else:
            painter.fillPath(dim, DIM)
        body = QPainterPath()
        body.addRoundedRect(QRectF(self.bubble.geometry()), RADIUS, RADIUS)
        painter.fillPath(body, QColor(palette.surface))
        painter.strokePath(body, QPen(QColor(palette.border), 1))

    # input ------------------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        event.accept()  # the window underneath only shows; it is not used during the tour

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_tour(False)
        elif key == Qt.Key.Key_Right:
            self._next()
        elif key == Qt.Key.Key_Left and self.step > 0:
            self.show_step(self.step - 1)
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._place()
        return False
