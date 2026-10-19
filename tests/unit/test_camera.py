import math
import time

import numpy as np
import pytest

from focuslab.camera.calibration import Calibration
from focuslab.camera.capture import Frame
from focuslab.camera.face_landmarker import FaceResult
from focuslab.camera.head_pose import brightness_quality, euler_from_matrix, face_quality
from focuslab.domain.models import CameraStatus
from focuslab.services.worker_manager import CameraFaceSource


def rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def rot_y(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


def as_matrix(rot, scale=1.0):
    m = np.eye(4)
    m[:3, :3] = rot * scale
    m[:3, 3] = (0, 0, -40)
    return m


def test_euler_identity_is_forward():
    yaw, pitch, roll = euler_from_matrix(np.eye(4))
    assert (yaw, pitch, roll) == pytest.approx((0, 0, 0))


def test_euler_yaw_and_pitch_signs_and_scale_invariance():
    yaw, pitch, _ = euler_from_matrix(as_matrix(rot_y(30), scale=1.7))
    assert yaw == pytest.approx(30) and pitch == pytest.approx(0, abs=1e-6)
    _, pitch, _ = euler_from_matrix(as_matrix(rot_x(20)))
    assert pitch == pytest.approx(-20)  # positive rotation about X tilts the face down


def test_quality_heuristics():
    assert brightness_quality(10) == 0 and brightness_quality(200) == 1
    face = np.array([[0.4, 0.3], [0.6, 0.7]])
    assert face_quality(face, 150) == pytest.approx(1.0)
    tiny = np.array([[0.5, 0.5], [0.52, 0.55]])
    assert face_quality(tiny, 150) < 0.2
    assert face_quality(face, 20) == 0


class FakeCapture:
    def __init__(self, status=CameraStatus.RUNNING):
        self._status = status
        self.started = self.stopped = 0
        self.frame = Frame(1, np.full((480, 640, 3), 120, np.uint8))

    @property
    def status(self):
        return self._status if self.started > self.stopped else CameraStatus.OFF

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def latest(self):
        return self.frame if self.started > self.stopped else None


class FakeLandmarker:
    def __init__(self, _path, result=None):
        self.result = result
        self.closed = False

    def detect(self, image, ts):
        return self.result

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_missing_model_never_opens_camera(tmp_path):
    cap = FakeCapture()
    src = CameraFaceSource(0, None, capture=cap)
    src.start()
    assert src.status is CameraStatus.MODEL_MISSING and cap.started == 0


def test_face_source_publishes_calibrated_observation_and_releases(tmp_path):
    cap = FakeCapture()
    result = FaceResult(np.array([[0.4, 0.3], [0.6, 0.7]]), as_matrix(rot_y(15)))
    lms = []

    def factory(path):
        lms.append(FakeLandmarker(path, result))
        return lms[-1]

    src = CameraFaceSource(
        0, tmp_path / "m.task", Calibration(yaw_offset=5), capture=cap, landmarker_factory=factory
    )
    src.overlay_enabled = True
    src.start()
    assert wait_for(lambda: src.latest() is not None)
    obs = src.latest()
    assert obs.face_visible and obs.yaw_deg == pytest.approx(10) and obs.quality > 0.5
    assert src.latest_raw_pose()[0] == pytest.approx(15)
    assert src.preview().shape == (240, 320, 3)
    src.stop()
    assert cap.stopped == 1 and lms[0].closed
    assert src.latest() is None and src.preview() is None


def test_no_face_frame_reports_not_visible(tmp_path):
    cap = FakeCapture()
    src = CameraFaceSource(0, tmp_path / "m.task", capture=cap, landmarker_factory=FakeLandmarker)
    src.start()
    assert wait_for(lambda: src.latest() is not None)
    assert src.latest().face_visible is False
    src.stop()


def test_model_error_releases_camera(tmp_path):
    cap = FakeCapture()

    def broken(path):
        raise RuntimeError("bad model")

    src = CameraFaceSource(0, tmp_path / "m.task", capture=cap, landmarker_factory=broken)
    src.start()
    assert wait_for(lambda: cap.stopped == 1)
    assert src.status is CameraStatus.MODEL_ERROR
    src.stop()
