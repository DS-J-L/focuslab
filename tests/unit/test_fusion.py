import pytest

from focuslab.camera.calibration import Calibration, calibrate
from focuslab.domain.models import (
    ActivityObservation,
    CameraStatus,
    FaceObservation,
    HeadDirection,
)
from focuslab.focus.fusion import AppRelation, FaceEvidence, fuse
from focuslab.focus.reasons import Reason

NOW = 10_000


def face(ts=NOW, visible=True, yaw=0.0, pitch=0.0, quality=0.9):
    return FaceObservation(ts, visible, yaw, pitch, quality)


def act(ts=NOW, name="code.exe", allowed=True, idle=1.0, available=True, locked=False):
    return ActivityObservation(ts, name, allowed, idle, available, locked)


def test_fresh_observations_are_used():
    f = fuse(NOW, face(), act(), camera_enabled=True)
    assert f.app is AppRelation.ALLOWED and f.face is FaceEvidence.FORWARD
    assert f.reasons == () and f.app_name == "code.exe" and f.idle_s == 1.0


def test_expired_face_observation_is_unknown_not_repeated():
    f = fuse(NOW, face(ts=NOW - 2_500), act(), camera_enabled=True)
    assert f.face is FaceEvidence.UNKNOWN
    assert Reason.FACE_STALE in f.reasons


def test_expired_activity_observation_is_unknown():
    f = fuse(NOW, face(), act(ts=NOW - 5_000), camera_enabled=True)
    assert f.app is AppRelation.UNKNOWN and f.app_name is None and f.idle_s is None
    assert Reason.ACTIVITY_STALE in f.reasons


def test_camera_disabled_is_off():
    f = fuse(NOW, None, act(), camera_enabled=False)
    assert f.face is FaceEvidence.OFF and Reason.CAMERA_OFF in f.reasons


def test_camera_error_status_is_unknown():
    f = fuse(NOW, face(), act(), camera_enabled=True, camera_status=CameraStatus.DISCONNECTED)
    assert f.face is FaceEvidence.UNKNOWN and Reason.CAMERA_UNAVAILABLE in f.reasons


def test_inference_failure_is_unknown():
    obs = face(visible=None, yaw=None, pitch=None, quality=None)
    f = fuse(NOW, obs, act(), camera_enabled=True)
    assert f.face is FaceEvidence.UNKNOWN


def test_dark_frame_without_face_is_low_quality_not_absent():
    obs = face(visible=False, yaw=None, pitch=None, quality=0.1)
    f = fuse(NOW, obs, act(), camera_enabled=True)
    assert f.face is FaceEvidence.UNKNOWN and Reason.FACE_LOW_QUALITY in f.reasons


def test_absent_face_with_good_frame():
    f = fuse(NOW, face(visible=False, yaw=None, pitch=None), act(), camera_enabled=True)
    assert f.face is FaceEvidence.ABSENT


def test_head_directions_use_calibration_limits():
    calib = Calibration(yaw_limit=20, down_limit=15, up_limit=20)
    kw = {"camera_enabled": True, "calibration": calib}
    assert fuse(NOW, face(yaw=25), act(), **kw).face is FaceEvidence.AWAY
    assert fuse(NOW, face(pitch=-20), act(), **kw).face is FaceEvidence.DOWN
    assert fuse(NOW, face(pitch=25), act(), **kw).face is FaceEvidence.AWAY
    assert fuse(NOW, face(yaw=10, pitch=-10), act(), **kw).face is FaceEvidence.FORWARD


def test_neutral_and_unrelated_apps():
    assert fuse(NOW, None, act(allowed=None), camera_enabled=False).app is AppRelation.NEUTRAL
    game = act(name="steam.exe", allowed=False)
    assert fuse(NOW, None, game, camera_enabled=False).app is AppRelation.UNRELATED


def test_browser_flag_and_lock():
    f = fuse(NOW, None, act(name="Chrome.exe"), camera_enabled=False)
    assert f.is_browser
    locked = act(name=None, allowed=None, locked=True)
    assert fuse(NOW, None, locked, camera_enabled=False).screen_locked


def test_calibration_learns_offsets_and_down_sign():
    forward = [(4.0, 10.0)] * 5
    left = [(-16.0, 10.0)] * 5
    right = [(26.0, 10.0)] * 5
    down = [(4.0, 40.0)] * 5  # this camera reports looking down as positive pitch
    c = calibrate(forward, left, right, down)
    assert c.calibrated and c.pitch_sign == -1.0
    yaw, pitch = c.relative(4.0, 40.0)
    assert yaw == 0 and pitch == -30.0
    assert c.classify(*c.relative(4.0, 40.0)) is HeadDirection.DOWN
    assert c.classify(*c.relative(24.0, 10.0)) is HeadDirection.FORWARD  # screen edge
    assert c.classify(*c.relative(50.0, 10.0)) is HeadDirection.AWAY
    assert Calibration.from_json(c.to_json()) == c


def test_calibration_json_fallback():
    assert Calibration.from_json("not json") == Calibration()
    assert Calibration.from_json(None) == Calibration()


@pytest.mark.parametrize(
    "name,domain,relation,support",
    [
        ("notepad.exe", None, AppRelation.POSSIBLY_RELATED, Reason.NOTE_TAKING_POSSIBLE),
        ("claude.exe", None, AppRelation.POSSIBLY_RELATED, Reason.AI_ASSISTANT_POSSIBLE),
        ("chrome.exe", "claude.ai", AppRelation.POSSIBLY_RELATED, Reason.AI_ASSISTANT_POSSIBLE),
        ("code.exe", None, AppRelation.POSSIBLY_RELATED, Reason.WORK_TOOL_POSSIBLE),
        ("leagueclient.exe", None, AppRelation.UNRELATED, None),
        ("kakaotalk.exe", None, AppRelation.UNRELATED, None),
        ("chrome.exe", "netflix.com", AppRelation.UNRELATED, None),
        ("unknown-tool.exe", None, AppRelation.UNRELATED, None),
    ],
)
def test_not_allowed_app_that_may_serve_the_task(name, domain, relation, support):
    obs = ActivityObservation(NOW, name, False, 1.0, True, domain=domain)
    f = fuse(NOW, None, obs, camera_enabled=False)
    assert f.app is relation and f.support == support


def test_allowed_app_carries_no_support_hint():
    f = fuse(NOW, None, act(name="notepad.exe", allowed=True), camera_enabled=False)
    assert f.app is AppRelation.ALLOWED and f.support is None
