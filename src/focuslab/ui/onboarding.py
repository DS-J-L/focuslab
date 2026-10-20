"""First-run setup: explicit opt-in to automatic recording, sign-in start and tray behavior.

Nothing is preselected that collects data; closing the dialog or choosing "Later" records
nothing. Every choice can be changed later in Settings.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.i18n import tr
from focuslab.ui.consent import RECORDING_TEXT


@dataclass(frozen=True)
class OnboardingChoice:
    recording: bool
    autostart: bool
    close_to_tray: bool
    idle_minutes: int


class OnboardingDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, idle_minutes: int = 5) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Welcome to FocusLab"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        title = QLabel(tr("Automatically record PC activity without a timer?"))
        title.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(title)
        text = QLabel(tr(RECORDING_TEXT), wordWrap=True, objectName="Muted")
        layout.addWidget(text)

        self.recording = QCheckBox(tr("I agree to automatic PC activity recording"))
        self.autostart = QCheckBox(tr("Start FocusLab in the tray when I sign in to Windows"))
        self.close_to_tray = QCheckBox(tr("Keep recording in the tray when the window is closed"))
        self.close_to_tray.setChecked(True)
        idle_row = QHBoxLayout()
        idle_row.addWidget(QLabel(tr("No-input threshold for idle time")))
        self.idle = QSpinBox()
        self.idle.setRange(1, 60)
        self.idle.setSuffix(tr(" min"))
        self.idle.setValue(idle_minutes)
        idle_row.addWidget(self.idle)
        idle_row.addStretch()
        for w in (self.recording, self.autostart, self.close_to_tray):
            layout.addWidget(w)
        layout.addLayout(idle_row)
        note = QLabel(
            tr(
                "The camera runs only in focus sessions you start. Browser "
                "site recording can be enabled separately in Settings. You "
                "can change all choices in Settings."
            ),
            wordWrap=True,
            objectName="Muted",
        )
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.save = buttons.addButton(tr("Save and start"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("Later"), QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.recording.toggled.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        on = self.recording.isChecked()
        for w in (self.autostart, self.close_to_tray, self.idle):
            w.setEnabled(on)

    def choice(self) -> OnboardingChoice:
        accepted = self.result() == QDialog.DialogCode.Accepted
        recording = accepted and self.recording.isChecked()
        return OnboardingChoice(
            recording=recording,
            autostart=recording and self.autostart.isChecked(),
            close_to_tray=self.close_to_tray.isChecked(),
            idle_minutes=self.idle.value(),
        )
