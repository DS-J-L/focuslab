"""A short tour for first-time users, shown once after first-run setup.

Every step can be skipped, and Settings > Appearance opens it again. It only explains;
it changes no setting and collects nothing.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from focuslab.i18n import tr

ICON_SIZE = 72


def guide_steps() -> list[tuple[str, str]]:
    "Title and text of each step, in the current language."
    return [
        (
            tr("A quick tour of FocusLab"),
            tr(
                "A one-minute tour of the basics. You can skip it now and open it again "
                "from Settings > Appearance."
            ),
        ),
        (
            tr("Home and Activity"),
            tr(
                "Home shows today's totals and your recent sessions. With automatic "
                "recording on, Activity shows which programs and sites you used, as a "
                "timeline you can correct."
            ),
        ),
        (
            tr("Start a focus session"),
            tr(
                "Press the round + at the bottom right of Home. Write a goal, choose a work "
                "mode and a target time, and check the allowed apps. The camera is optional "
                "and stays off unless you turn it on."
            ),
        ),
        (
            tr("Work modes"),
            tr(
                "A work mode decides what counts as normal work, for example whether looking "
                "down at paper is work. Add your own modes with their own allowed apps under "
                "Settings > Work modes."
            ),
        ),
        (
            tr("During and after a session"),
            tr(
                "The parrots on the overlay pause, end, or start a break. Reports show each "
                "session afterwards, and you can correct any estimate. Estimates describe "
                "observable behavior; they are not measurements of attention."
            ),
        ),
    ]


class GuideDialog(QDialog):
    "Back / Next through the steps; Skip, Esc or closing the window ends it early."

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("FocusLab guide"))
        self.setMinimumWidth(480)
        self._steps = guide_steps()
        self.step = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        self.icon = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(Path(__file__).with_name("icons") / "parrot-telescope.png"))
        if not pixmap.isNull():
            self.icon.setPixmap(
                pixmap.scaled(
                    ICON_SIZE,
                    ICON_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(self.icon)
        self.counter = QLabel(objectName="Muted")
        layout.addWidget(self.counter)
        self.title = QLabel(objectName="PopoverTitle", wordWrap=True)
        layout.addWidget(self.title)
        self.text = QLabel(wordWrap=True)
        self.text.setMinimumHeight(72)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.text, 1)

        buttons = QHBoxLayout()
        self.skip = QPushButton(tr("Skip guide"))
        self.skip.clicked.connect(self.reject)
        self.back = QPushButton(tr("Back"))
        self.back.clicked.connect(lambda: self.show_step(self.step - 1))
        self.next = QPushButton(objectName="Primary")
        self.next.setDefault(True)
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.skip)
        buttons.addStretch()
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        self.show_step(0)

    @property
    def last(self) -> bool:
        return self.step == len(self._steps) - 1

    def show_step(self, step: int) -> None:
        self.step = max(0, min(step, len(self._steps) - 1))
        title, text = self._steps[self.step]
        self.counter.setText(tr("Step {p0} of {p1}", p0=self.step + 1, p1=len(self._steps)))
        self.title.setText(title)
        self.text.setText(text)
        self.icon.setVisible(self.step == 0)
        self.back.setEnabled(self.step > 0)
        self.skip.setVisible(not self.last)
        self.next.setText(tr("Get started") if self.last else tr("Next"))

    def _next(self) -> None:
        if self.last:
            self.accept()
        else:
            self.show_step(self.step + 1)
