import pytest

from focuslab.domain.models import (
    CameraStatus,
    FocusState,
    SessionConfig,
    SessionMode,
    SessionStatus,
)
from focuslab.focus.reasons import Reason
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.services.session_service import (
    InvalidTransition,
    Lifecycle,
    SessionLifecycle,
    SessionService,
)

APPS = ("code.exe",)


def config(camera=True, minutes=0, mode=SessionMode.CODING):
    return SessionConfig("테스트", mode, minutes, APPS, camera)


@pytest.fixture
def make_service(tmp_path, clock):
    created = []

    def make(face_script=((3600, "forward"),), activity_script=((3600, "code.exe", "active"),)):
        faces = []

        def face_factory(cfg):
            src = MockFaceSource(face_script, clock)
            faces.append(src)
            return src

        svc = SessionService(
            tmp_path / "s.db",
            face_factory=face_factory,
            activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, activity_script),
            clock=clock,
            auto_tick=False,
        )
        svc.faces = faces
        created.append(svc)
        return svc

    yield make
    for svc in created:
        svc.shutdown()


def tick(svc, clock, n):
    out = []
    for _ in range(n):
        clock.advance(1)
        out.append(svc.tick())
    return out


def test_lifecycle_transitions():
    lc = SessionLifecycle()
    assert lc.apply("start") is Lifecycle.RUNNING
    assert lc.apply("pause") is Lifecycle.PAUSED
    with pytest.raises(InvalidTransition):
        lc.apply("pause")
    assert lc.apply("resume") is Lifecycle.RUNNING
    assert lc.apply("finish") is Lifecycle.FINISHED
    with pytest.raises(InvalidTransition):
        lc.apply("resume")


def test_running_session_records_one_sample_per_second(make_service, clock):
    svc = make_service()
    sid = svc.start(config())
    decisions = tick(svc, clock, 5)
    assert all(d.state is FocusState.ON_TASK for d in decisions)
    snap = svc.snapshot()
    assert snap.active_s == 5 and snap.seconds[FocusState.ON_TASK] == 5
    assert snap.camera_status is CameraStatus.RUNNING
    assert len(svc.repository.samples(sid)) == 5
    assert len(svc.repository.segments(sid)) == 1


def test_pause_releases_camera_and_stops_sampling(make_service, clock):
    svc = make_service()
    sid = svc.start(config())
    tick(svc, clock, 3)
    svc.pause()
    face = svc.faces[0]
    assert face.stop_count == 1 and face.status is CameraStatus.OFF
    assert tick(svc, clock, 10) == [None] * 10
    assert svc.repository.get_session(sid).status is SessionStatus.PAUSED
    svc.resume()
    assert face.start_count == 2
    tick(svc, clock, 2)
    svc.finish()
    rec = svc.repository.get_session(sid)
    assert rec.status is SessionStatus.FINISHED and rec.ended_at_utc
    assert rec.paused_seconds == 10
    assert [s.second_offset for s in svc.repository.samples(sid)] == list(range(5))
    # pause splits segments even when the state is unchanged
    assert len(svc.repository.segments(sid)) == 2


def test_break_is_recorded_separately(make_service, clock):
    svc = make_service()
    svc.start(config())
    tick(svc, clock, 2)
    svc.set_break(True)
    tick(svc, clock, 3)
    svc.set_break(False)
    tick(svc, clock, 1)
    snap = svc.snapshot()
    assert snap.seconds[FocusState.BREAK] == 3
    assert snap.decision.state is FocusState.ON_TASK


def test_camera_off_session_works_on_pc_activity(make_service, clock):
    svc = make_service()
    sid = svc.start(config(camera=False))
    decisions = tick(svc, clock, 3)
    assert svc.faces == []
    assert all(d.state is FocusState.ON_TASK for d in decisions)
    assert Reason.CAMERA_OFF in svc.repository.samples(sid)[0].reason_codes


def test_planned_time_finishes_session(make_service, clock):
    svc = make_service()
    sid = svc.start(config(minutes=1))
    tick(svc, clock, 61)
    snap = svc.snapshot()
    assert snap.lifecycle is Lifecycle.FINISHED and snap.planned_reached
    assert len(svc.repository.samples(sid)) == 60
    assert svc.faces[0].status is CameraStatus.OFF


def test_observation_gap_is_unknown(make_service, clock):
    svc = make_service()
    sid = svc.start(config())
    tick(svc, clock, 2)
    clock.advance(30)  # e.g. system sleep
    svc.tick()
    states = [s.state for s in svc.repository.samples(sid)]
    assert len(states) == 32
    assert states[2:31] == [FocusState.UNKNOWN] * 29
    assert Reason.OBSERVATION_GAP in svc.repository.samples(sid)[5].reason_codes


def test_late_ticks_do_not_drift_or_create_gaps(make_service, clock):
    svc = make_service()
    sid = svc.start(config())
    for _ in range(100):
        clock.advance(1.02)  # every tick 20 ms late
        svc.tick()
    samples = svc.repository.samples(sid)
    assert abs(len(samples) - 102) <= 1
    assert [s.second_offset for s in samples] == list(range(len(samples)))
    assert not any(Reason.OBSERVATION_GAP in s.reason_codes for s in samples)


def test_jittery_ticks_record_one_sample_each(make_service, clock):
    svc = make_service()
    sid = svc.start(config())
    for i in range(100):
        clock.advance(0.9 if i % 2 else 1.1)
        svc.tick()
    assert len(svc.repository.samples(sid)) == 100


def test_live_correction_applies_to_current_segment(make_service, clock):
    svc = make_service(activity_script=((3600, "game.exe", "active"),))
    sid = svc.start(config())
    tick(svc, clock, 20)
    assert svc.snapshot().decision.state is FocusState.POSSIBLY_OFF_TASK
    assert svc.correct_current(FocusState.ON_TASK)
    tick(svc, clock, 2)
    seg = svc.repository.segments(sid)[-1]
    assert seg.state is FocusState.POSSIBLY_OFF_TASK and seg.corrected_label is FocusState.ON_TASK
    assert svc.snapshot().segments[-1].corrected_label is FocusState.ON_TASK


def test_invalid_actions_raise(make_service):
    svc = make_service()
    with pytest.raises(InvalidTransition):
        svc.pause()
    with pytest.raises(InvalidTransition):
        svc.set_break(True)
    assert svc.finish() is None


def test_session_can_restart_after_finish(make_service, clock):
    svc = make_service()
    first = svc.start(config())
    tick(svc, clock, 1)
    svc.finish()
    second = svc.start(config())
    assert second != first and svc.snapshot().active_s == 0


def test_recover_interrupted_after_crash(tmp_path, clock):
    def make():
        return SessionService(
            tmp_path / "crash.db",
            face_factory=lambda c: None,
            activity_factory=lambda c: MockActivitySource(c.allowed_apps),
            clock=clock,
            auto_tick=False,
        )

    crashed = make()
    sid = crashed.start(config(camera=False))
    crashed.repository.conn.close()  # simulate the process dying without finish()
    restarted = make()
    assert restarted.recover_interrupted() == [sid]
    assert restarted.repository.get_session(sid).status is SessionStatus.INTERRUPTED
    restarted.shutdown()
