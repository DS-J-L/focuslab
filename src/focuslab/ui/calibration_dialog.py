"""Four-step head pose calibration (centre, left edge, right edge, desk). Camera is released
when the dialog closes; only the resulting angles are saved."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focuslab.camera.calibration import Calibration, Pose, calibrate
from focuslab.config import face_model_path
from focuslab.domain.models import CameraStatus
from focuslab.i18n import tr
from focuslab.services.worker_manager import CameraFaceSource
from focuslab.ui.theme import CAMERA_LABELS
from focuslab.ui.widgets import frame_pixmap, preview_label

STEPS = [
    ("1/4 Center", "Look at the center of the screen in your usual posture."),
    ("2/4 Left edge", "Turn your head toward the left edge of the screen."),
    ("3/4 Right edge", "Turn your head toward the right edge of the screen."),
    ("4/4 Down", "Look at your keyboard or a notebook on your desk."),
]
COLLECT_MS = 2500


class CalibrationDialog(QDialog):
    def __init__(self, camera_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Head pose calibration"))
        self.setModal(True)
        self.result_calibration: Calibration | None = None
        self._source = CameraFaceSource(camera_index, face_model_path())
        self._step = 0
        self._samples: list[list[Pose]] = [[] for _ in STEPS]
        self._collect_left = 0

        layout = QVBoxLayout(self)
        self.step_label = QLabel(styleSheet="font-size:18px; font-weight:700;")
        self.instruction = QLabel(wordWrap=True)
        self.preview = preview_label(tr("Opening camera…"))
        self.status = QLabel(objectName="Muted", wordWrap=True)
        self.progress = QProgressBar()
        self.progress.setRange(0, COLLECT_MS)
        self.progress.setTextVisible(False)
        buttons = QHBoxLayout()
        self.measure = QPushButton(tr("Measure"), objectName="Primary")
        self.measure.clicked.connect(self._begin_step)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.measure)
        for w in (self.step_label, self.instruction, self.preview, self.status, self.progress):
            layout.addWidget(w)
        layout.addWidget(
            QLabel(
                tr("Video is never saved. The camera is released when calibration finishes."),
                objectName="Muted",
            )
        )
        layout.addLayout(buttons)

        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._tick)
        self._show_step()
        self._source.start()
        self._timer.start()

    def _show_step(self) -> None:
        title, text = STEPS[self._step]
        self.step_label.setText(tr(title))
        self.instruction.setText(tr(text) + tr(" Press [Measure] when ready (about 2.5 seconds)."))
        self.progress.setValue(0)

    def _begin_step(self) -> None:
        self._samples[self._step].clear()
        self._collect_left = COLLECT_MS
        self.measure.setEnabled(False)

    def _tick(self) -> None:
        frame = self._source.preview()
        if frame is not None:
            self.preview.setPixmap(frame_pixmap(frame))
        status = self._source.status
        pose = self._source.latest_raw_pose()
        if status is not CameraStatus.RUNNING:
            self.status.setText(CAMERA_LABELS[status])
            self.measure.setEnabled(False)
            return
        self.status.setText(
            tr("Face detected") if pose else tr("Face not visible. Please sit facing the camera.")
        )
        if self._collect_left <= 0:
            self.measure.setEnabled(True)
            return
        if pose:
            self._samples[self._step].append(pose)
        self._collect_left -= self._timer.interval()
        self.progress.setValue(COLLECT_MS - self._collect_left)
        if self._collect_left > 0:
            return
        if len(self._samples[self._step]) < 5:
            self.instruction.setText(
                tr("Not enough face observations. Please press [Measure] again.")
            )
            return
        self._step += 1
        if self._step < len(STEPS):
            self._show_step()
            return
        self.result_calibration = calibrate(*self._samples)
        self.accept()

    def done(self, result: int) -> None:  # accept/reject/close all end here
        self._timer.stop()
        self._source.stop()
        super().done(result)
