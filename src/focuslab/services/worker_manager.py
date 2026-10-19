"""Camera + face inference workers behind the ``FaceSource`` interface.

Capture and inference run on separate threads; the UI only polls the latest
observation and an optional small preview, all held in memory. ``stop`` joins
both threads and releases the camera device.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from focuslab.camera.calibration import Calibration
from focuslab.camera.capture import CameraCapture
from focuslab.camera.head_pose import brightness_quality, euler_from_matrix, face_quality
from focuslab.domain.models import CameraStatus, FaceObservation
from focuslab.domain.protocols import Clock, MonotonicClock

log = logging.getLogger(__name__)

PREVIEW_SIZE = (320, 240)


class CameraFaceSource:
    def __init__(
        self,
        camera_index: int,
        model_path: Path | None,
        calibration: Calibration | None = None,
        clock: Clock | None = None,
        target_fps: float = 10.0,
        capture: CameraCapture | None = None,
        landmarker_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        self._capture = capture or CameraCapture(camera_index)
        self._landmarker_factory = landmarker_factory
        self._model_path = model_path
        self._calibration = calibration or Calibration()
        self._clock = clock or MonotonicClock()
        self._period = 1.0 / target_fps
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._model_error = False
        self._observation: FaceObservation | None = None
        self._raw_pose: tuple[float, float] | None = None
        self._preview: np.ndarray | None = None
        self.preview_enabled = True
        self.overlay_enabled = False

    @property
    def status(self) -> CameraStatus:
        if self._model_path is None:
            return CameraStatus.MODEL_MISSING
        if self._model_error:
            return CameraStatus.MODEL_ERROR
        return self._capture.status

    def start(self) -> None:
        if self._model_path is None or (self._thread and self._thread.is_alive()):
            return
        self._model_error = False
        self._stop.clear()
        self._capture.start()
        self._thread = threading.Thread(target=self._run, name="focuslab-face", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._capture.stop()
        with self._lock:
            self._observation = None
            self._raw_pose = None
            self._preview = None

    def latest(self) -> FaceObservation | None:
        with self._lock:
            return self._observation

    def latest_raw_pose(self) -> tuple[float, float] | None:
        """Uncalibrated (yaw, pitch) for the calibration wizard."""
        with self._lock:
            return self._raw_pose

    def preview(self) -> np.ndarray | None:
        """Small mirrored RGB preview, or None. Never written to disk."""
        with self._lock:
            return self._preview

    def _run(self) -> None:
        from focuslab.camera.face_landmarker import FaceLandmarkerAdapter

        try:
            landmarker = (self._landmarker_factory or FaceLandmarkerAdapter)(self._model_path)
        except Exception:
            log.exception("face model could not be loaded; continuing without camera evidence")
            self._model_error = True
            self._capture.stop()  # no reason to keep the camera open
            return
        last_id = None
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                frame = self._capture.latest()
                if frame is None or frame.id == last_id:
                    self._stop.wait(0.02)
                    continue
                last_id = frame.id
                self._process(landmarker, frame.image)
                self._stop.wait(max(0.0, self._period - (time.monotonic() - started)))
        finally:
            landmarker.close()

    def _process(self, landmarker: Any, image: np.ndarray) -> None:
        import cv2

        now = self._clock.monotonic_ms()
        gray_mean = float(image[::8, ::8].mean())
        result = landmarker.detect(image, now)
        raw_pose = None
        if result is None:
            obs = FaceObservation(now, False, None, None, brightness_quality(gray_mean))
        else:
            quality = face_quality(result.landmarks_xy, gray_mean)
            yaw = pitch = None
            if result.matrix is not None:
                raw_yaw, raw_pitch, _ = euler_from_matrix(result.matrix)
                raw_pose = (raw_yaw, raw_pitch)
                yaw, pitch = self._calibration.relative(raw_yaw, raw_pitch)
            obs = FaceObservation(now, True, yaw, pitch, quality)

        preview = None
        if self.preview_enabled:
            small = cv2.resize(image, PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
            if self.overlay_enabled and result is not None:
                w, h = PREVIEW_SIZE
                for x, y in result.landmarks_xy[::6]:
                    cv2.circle(small, (int(x * w), int(y * h)), 1, (80, 220, 120), -1)
            preview = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
        with self._lock:
            self._observation = obs
            self._raw_pose = raw_pose
            self._preview = preview
