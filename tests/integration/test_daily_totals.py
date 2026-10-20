"""Manual focus sessions are counted on the local day each second happened."""

from datetime import datetime, timedelta

from focuslab.activity.stats import local_day_bounds
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.mock_sources import MockActivitySource
from focuslab.services.export_service import daily_totals
from focuslab.services.session_service import SessionService

CODING = ((3600, "code.exe", "active"),)


def _service(path, clock, wall_start_ms):
    base = clock.ms
    return SessionService(
        path, face_factory=lambda c: None,
        activity_factory=lambda c: MockActivitySource(c.allowed_apps, CODING),
        clock=clock, auto_tick=False, wall=lambda: wall_start_ms + clock.ms - base,
    )


def _tick(svc, clock, n):
    for _ in range(n):
        clock.advance(1)
        svc.tick()


def test_a_session_past_midnight_counts_on_both_days(tmp_path, clock):
    today = datetime.now().astimezone().date()
    midnight, _ = local_day_bounds(today)
    svc = _service(tmp_path / "d.db", clock, midnight - 3_000)
    try:
        sid = svc.start(SessionConfig("자정", SessionMode.CODING, 0, ("code.exe",), False))
        _tick(svc, clock, 2)  # 23:59:57 and 23:59:58
        svc.pause()
        clock.advance(10)
        svc.resume()
        _tick(svc, clock, 3)  # after midnight
        svc.finish()
        days = dict(daily_totals(svc.repository, 7, today))
        samples = svc.repository.samples(sid)
    finally:
        svc.shutdown()
    yesterday = today - timedelta(days=1)
    assert days[yesterday][FocusState.ON_TASK] == 2
    assert days[today][FocusState.ON_TASK] == 3
    assert sum(sum(c.values()) for c in days.values()) == len(samples) == 5


def test_observation_gaps_are_dated_where_they_happened(tmp_path, clock):
    midnight, _ = local_day_bounds(datetime.now().astimezone().date())
    svc = _service(tmp_path / "g.db", clock, midnight - 3_000)
    try:
        sid = svc.start(SessionConfig("공백", SessionMode.CODING, 0, ("code.exe",), False))
        _tick(svc, clock, 1)
        clock.advance(10)  # e.g. a short system sleep across midnight
        svc.tick()
        times = [s.at_ms for s in svc.repository.samples(sid)]
    finally:
        svc.shutdown()
    assert times == [midnight - 3_000 + i * 1000 for i in range(11)]
