"""Activity timeline + focus session (mock camera) + automatic sessions on one database."""

from focuslab.activity.camera_overlay import attended_ms, overlay, session_samples
from focuslab.domain.activity import ActivitySpan, Category, SpanKind
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.services.activity_service import rebuild_auto_sessions, stored_auto_sessions
from focuslab.services.session_service import SessionService
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.repository import epoch_ms

T0 = 1_760_000_000_000


def run_focus_session(db, clock):
    """VS Code in front, face visible 30 s, then the user walks away for 90 s."""
    svc = SessionService(
        db,
        face_factory=lambda cfg: MockFaceSource(((30, "forward"), (90, "absent")), clock,
                                                loop=False),
        activity_factory=lambda cfg: MockActivitySource(
            cfg.allowed_apps, ((30, "code.exe", "active"), (90, "code.exe", "idle")), loop=False
        ),
        clock=clock,
        auto_tick=False,
        wall=lambda: T0 + clock.ms - base,
    )
    base = clock.ms
    sid = svc.start(SessionConfig("코딩", SessionMode.CODING, 0, ("code.exe",), True))
    for _ in range(120):
        clock.advance(1)
        svc.tick()
    svc.finish()
    with svc.lock:
        svc.repository.conn.execute(  # place the session at the same time as the spans
            "UPDATE session SET started_at_utc = ?, ended_at_utc = ? WHERE id = ?",
            ("2025-10-09T08:53:20+00:00", "2025-10-09T08:55:20+00:00", sid),
        )
    return svc, sid


def test_camera_away_reduces_attended_time_but_gaze_alone_does_not(tmp_path, clock):
    svc, sid = run_focus_session(tmp_path / "f.db", clock)
    try:
        assert epoch_ms("2025-10-09T08:53:20+00:00") == T0
        conn = svc.repository.conn
        activity = ActivityRepository(conn)
        span_id = activity.insert_span(ActivitySpan(T0, T0 + 120_000, SpanKind.ACTIVE, "code.exe"))
        spans = activity.spans_between(T0, T0 + 120_000)
        samples = session_samples(svc.repository, T0, T0 + 120_000)
        assert len(samples) == 120 and {s for _, s, _ in samples} == {sid}
        ov = overlay(spans, samples)[span_id]
        assert ov.observed_s == 120 and ov.camera_s == 120
        assert ov.face_absent_s >= 80 and 0 < ov.away_s < 90
        assert attended_ms(spans[0], ov) == 120_000 - ov.away_s * 1000

        # The user says it was still work (reading on paper): their correction wins.
        away = next(s for s in svc.repository.segments(sid) if s.state is FocusState.AWAY)
        svc.repository.set_feedback(away.event_id, FocusState.ON_TASK)
        corrected = overlay(spans, session_samples(svc.repository, T0, T0 + 120_000))[span_id]
        assert corrected.away_s == 0 and attended_ms(spans[0], corrected) == 120_000
    finally:
        svc.shutdown()


def test_rebuilding_auto_sessions_is_idempotent_and_links_the_focus_session(tmp_path, clock):
    svc, sid = run_focus_session(tmp_path / "f.db", clock)
    try:
        conn = svc.repository.conn
        activity = ActivityRepository(conn)
        minute = 60_000
        for start, end, exe in ((0, 20, "code.exe"), (20, 30, "chrome.exe")):
            activity.insert_span(ActivitySpan(T0 + start * minute, T0 + end * minute,
                                              SpanKind.ACTIVE, exe))
        activity.insert_span(ActivitySpan(T0 + 30 * minute, T0 + 45 * minute, SpanKind.IDLE))
        activity.insert_span(ActivitySpan(T0 + 45 * minute, T0 + 70 * minute,
                                          SpanKind.ACTIVE, "winword.exe"))
        window = (T0, T0 + 24 * 60 * minute)
        first = rebuild_auto_sessions(conn, *window)
        again = rebuild_auto_sessions(conn, *window)
        stored = stored_auto_sessions(conn, *window)
        assert len(first) == len(again) == len(stored) == 3
        # 10 min in a browser without a known site is an observed change of work, not
        # "off task"; the 15 min idle ends that session
        assert [(s.category, s.manual_session_id) for s in stored] == [
            (Category.DEVELOPMENT, sid), (Category.UNKNOWN, None),
            (Category.DOCUMENTATION, None),
        ]
        assert stored[0].active_ms == 20 * minute and stored[2].active_ms == 25 * minute
    finally:
        svc.shutdown()
