"""First-run setup: explicit opt-in to automatic recording, sign-in start and tray behavior.

Nothing is preselected that collects data; closing the dialog or choosing "나중에" records
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
        self.setWindowTitle("FocusLab 시작 설정")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        title = QLabel("타이머 없이 PC 활동을 자동으로 기록할까요?")
        title.setStyleSheet("font-size:16px; font-weight:700;")
        layout.addWidget(title)
        text = QLabel(RECORDING_TEXT, wordWrap=True, objectName="Muted")
        layout.addWidget(text)

        self.recording = QCheckBox("PC 활동 자동 기록에 동의합니다")
        self.autostart = QCheckBox("Windows에 로그인하면 FocusLab을 트레이로 자동 실행")
        self.close_to_tray = QCheckBox("창을 닫아도 트레이에서 계속 기록")
        self.close_to_tray.setChecked(True)
        idle_row = QHBoxLayout()
        idle_row.addWidget(QLabel("입력이 없으면 자리 비움(유휴)으로 보는 시간"))
        self.idle = QSpinBox()
        self.idle.setRange(1, 60)
        self.idle.setSuffix(" 분")
        self.idle.setValue(idle_minutes)
        idle_row.addWidget(self.idle)
        idle_row.addStretch()
        for w in (self.recording, self.autostart, self.close_to_tray):
            layout.addWidget(w)
        layout.addLayout(idle_row)
        note = QLabel(
            "카메라는 직접 시작한 집중 세션에서만 켜지며, 브라우저 사이트 기록은 설정에서 따로"
            " 켤 수 있습니다. 모든 선택은 설정에서 바꿀 수 있습니다.",
            wordWrap=True, objectName="Muted",
        )
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.save = buttons.addButton("저장하고 시작", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("나중에", QDialogButtonBox.ButtonRole.RejectRole)
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
