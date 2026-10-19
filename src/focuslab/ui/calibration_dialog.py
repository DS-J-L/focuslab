"""Four-step head pose calibration (centre, left edge, right edge, desk). Camera is released
when the dialog closes; only the resulting angles are saved."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
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
from focuslab.services.worker_manager import CameraFaceSource
from focuslab.ui.theme import CAMERA_LABELS

STEPS = [
    ("1/4 정면", "평소 자세로 화면 중앙을 바라보세요."),
    ("2/4 왼쪽 끝", "고개를 돌려 화면의 왼쪽 끝을 바라보세요."),
    ("3/4 오른쪽 끝", "고개를 돌려 화면의 오른쪽 끝을 바라보세요."),
    ("4/4 아래", "키보드나 책상 위 노트를 바라보세요."),
]
COLLECT_MS = 2500


class CalibrationDialog(QDialog):
    def __init__(self, camera_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("머리 방향 보정")
        self.setModal(True)
        self.result_calibration: Calibration | None = None
        self._source = CameraFaceSource(camera_index, face_model_path())
        self._step = 0
        self._samples: list[list[Pose]] = [[] for _ in STEPS]
        self._collect_left = 0

        layout = QVBoxLayout(self)
        self.step_label = QLabel(styleSheet="font-size:18px; font-weight:700;")
        self.instruction = QLabel(wordWrap=True)
        self.preview = QLabel("카메라 여는 중…", alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(320, 240)
        self.preview.setStyleSheet("background:#1F2430; color:#8C94A6; border-radius:8px;")
        self.status = QLabel(objectName="Muted", wordWrap=True)
        self.progress = QProgressBar()
        self.progress.setRange(0, COLLECT_MS)
        self.progress.setTextVisible(False)
        buttons = QHBoxLayout()
        self.measure = QPushButton("측정", objectName="Primary")
        self.measure.clicked.connect(self._begin_step)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.measure)
        for w in (self.step_label, self.instruction, self.preview, self.status, self.progress):
            layout.addWidget(w)
        layout.addWidget(QLabel("영상은 저장되지 않으며 보정 후 카메라를 즉시 해제합니다.",
                                objectName="Muted"))
        layout.addLayout(buttons)

        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._tick)
        self._show_step()
        self._source.start()
        self._timer.start()

    def _show_step(self) -> None:
        title, text = STEPS[self._step]
        self.step_label.setText(title)
        self.instruction.setText(text + " 준비되면 [측정]을 누르세요 (약 2.5초).")
        self.progress.setValue(0)

    def _begin_step(self) -> None:
        self._samples[self._step].clear()
        self._collect_left = COLLECT_MS
        self.measure.setEnabled(False)

    def _tick(self) -> None:
        frame = self._source.preview()
        if frame is not None:
            h, w, _ = frame.shape
            image = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            self.preview.setPixmap(QPixmap.fromImage(image))
        status = self._source.status
        pose = self._source.latest_raw_pose()
        if status is not CameraStatus.RUNNING:
            self.status.setText(CAMERA_LABELS[status])
            self.measure.setEnabled(False)
            return
        self.status.setText(
            "얼굴 인식됨" if pose else "얼굴이 보이지 않습니다. 카메라를 향해 앉아 주세요."
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
                "얼굴을 충분히 인식하지 못했습니다. 다시 [측정]을 눌러 주세요."
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
