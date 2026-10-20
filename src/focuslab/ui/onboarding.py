"""First-run setup: interface language, explicit opt-in to automatic recording, sign-in start
and tray behavior.

Nothing is preselected that collects data; closing the dialog or choosing "Later" records
nothing. Every choice can be changed later in Settings.
"""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.i18n import (
    SUPPORTED_LANGUAGES,
    get_language,
    install_qt_translator,
    set_language,
    tr,
)
from focuslab.ui.consent import RECORDING_TEXT


@dataclass(frozen=True)
class OnboardingChoice:
    recording: bool
    autostart: bool
    close_to_tray: bool
    idle_minutes: int
    language: str


class OnboardingDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, idle_minutes: int = 5) -> None:
        super().__init__(parent)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        # Nothing else is running yet, so the language applies immediately, not on restart.
        language_row = QHBoxLayout()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(get_language()))
        language_row.addWidget(self.language_label)
        language_row.addWidget(self.language_combo)
        language_row.addStretch()
        layout.addLayout(language_row)

        self.title = QLabel()
        self.title.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(self.title)
        self.text = QLabel(wordWrap=True, objectName="Muted")
        layout.addWidget(self.text)

        self.recording = QCheckBox()
        self.autostart = QCheckBox()
        self.close_to_tray = QCheckBox()
        self.close_to_tray.setChecked(True)
        idle_row = QHBoxLayout()
        self.idle_label = QLabel()
        idle_row.addWidget(self.idle_label)
        self.idle = QSpinBox()
        self.idle.setRange(1, 60)
        self.idle.setValue(idle_minutes)
        idle_row.addWidget(self.idle)
        idle_row.addStretch()
        for w in (self.recording, self.autostart, self.close_to_tray):
            layout.addWidget(w)
        layout.addLayout(idle_row)
        self.note = QLabel(wordWrap=True, objectName="Muted")
        layout.addWidget(self.note)

        buttons = QDialogButtonBox()
        self.save = buttons.addButton("", QDialogButtonBox.ButtonRole.AcceptRole)
        self.later = buttons.addButton("", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.language_combo.currentIndexChanged.connect(self._language_changed)
        self.recording.toggled.connect(self._sync)
        self._retranslate()
        self._sync()

    def _language_changed(self) -> None:
        set_language(self.language_combo.currentData())
        app = QApplication.instance()
        if app is not None:
            install_qt_translator(app)
        self._retranslate()

    def _retranslate(self) -> None:
        self.setWindowTitle(tr("Welcome to FocusLab"))
        self.language_label.setText(tr("Language"))
        self.title.setText(tr("Automatically record PC activity without a timer?"))
        self.text.setText(tr(RECORDING_TEXT))
        self.recording.setText(tr("I agree to automatic PC activity recording"))
        self.autostart.setText(tr("Start FocusLab in the tray when I sign in to Windows"))
        self.close_to_tray.setText(tr("Keep recording in the tray when the window is closed"))
        self.idle_label.setText(tr("No-input threshold for idle time"))
        self.idle.setSuffix(tr(" min"))
        self.note.setText(
            tr(
                "The camera runs only in focus sessions you start. Browser "
                "site recording can be enabled separately in Settings. You "
                "can change all choices in Settings."
            )
        )
        self.save.setText(tr("Save and start"))
        self.later.setText(tr("Later"))

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
            language=self.language_combo.currentData(),
        )
