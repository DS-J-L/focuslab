"""Synthetic demo sessions run through the real pipeline (mock sensors, simulated clock).

Used by ``focuslab --seed-demo`` so reports can be explored without recording anything.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from focuslab.config import DEFAULT_ALLOWED_APPS
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.i18n import tr
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.services.session_service import SessionService


class _SimClock:
    def __init__(self) -> None:
        self.ms = 0

    def monotonic_ms(self) -> int:
        return self.ms


# (days ago, hour, goal, mode, minutes, camera, face script, activity script)
DEMO_SESSIONS = [
    (
        4,
        20,
        "Demo: solve algorithm problems",
        SessionMode.CODING,
        25,
        True,
        ((300, "forward"), (40, "down"), (25, "away"), (400, "forward"), (30, "absent")),
        (
            (420, "code.exe", "active"),
            (40, "chrome.exe", "active"),
            (30, "kakaotalk.exe", "idle"),
            (300, "code.exe", "active"),
            (60, "code.exe", "idle"),
        ),
    ),
    (
        2,
        14,
        "Demo: watch a lecture",
        SessionMode.LECTURE,
        30,
        False,
        ((60, "forward"),),
        (
            (600, "chrome.exe", "idle"),
            (45, "youtube_music.exe", "active"),
            (500, "chrome.exe", "idle"),
        ),
    ),
    (
        1,
        21,
        "Demo: read a paper and take notes",
        SessionMode.READING_WRITING,
        20,
        True,
        ((200, "down"), (90, "forward"), (40, "absent"), (300, "down"), (80, "away")),
        ((900, "acrobat.exe", "idle"), (60, "slack.exe", "active")),
    ),
    (
        0,
        9,
        "Demo: refactor a project",
        SessionMode.CODING,
        25,
        True,
        ((500, "forward"), (25, "absent"), (300, "forward"), (20, "away")),
        ((360, "code.exe", "active"), (25, "game.exe", "active"), (500, "code.exe", "active")),
    ),
]


def seed_demo_sessions(db_path: Path) -> list[int]:
    clock = _SimClock()
    scripts: dict[str, tuple] = {}
    svc = SessionService(
        db_path,
        face_factory=lambda cfg: MockFaceSource(scripts["face"], clock),
        activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, scripts["activity"]),
        clock=clock,
        auto_tick=False,
    )
    now = datetime.now().astimezone()
    ids = []
    for days_ago, hour, goal, mode, minutes, camera, face, activity in DEMO_SESSIONS:
        scripts["face"], scripts["activity"] = face, activity
        allowed = DEFAULT_ALLOWED_APPS[mode] or ("code.exe",)
        sid = svc.start(SessionConfig(goal, mode, minutes, allowed, camera))
        for second in range(minutes * 60):
            if second == minutes * 30:  # a short user break in the middle
                svc.set_break(True)
            if second == minutes * 30 + 120:
                svc.set_break(False)
            clock.ms += 1000
            svc.tick()
        start = (now - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0)
        if start + timedelta(minutes=minutes) > now:  # keep demo sessions in the past
            start = now - timedelta(minutes=minutes + 30)
        end = start + timedelta(minutes=minutes)
        with svc.lock:
            repo = svc.repository
            # Samples were taken on a simulated clock: place them at the faked start instead.
            repo.conn.execute(
                "UPDATE state_sample SET at_ms = ? + second_offset * 1000 WHERE session_id = ?",
                (int(start.timestamp() * 1000), sid),
            )
            repo.conn.execute(
                "UPDATE session SET started_at_utc = ?, ended_at_utc = ?, self_report = ?"
                " WHERE id = ?",
                (
                    start.astimezone(UTC).isoformat(timespec="seconds"),
                    end.astimezone(UTC).isoformat(timespec="seconds"),
                    "PARTIAL",
                    sid,
                ),
            )
            first_off = next(
                (s for s in repo.segments(sid) if s.state is FocusState.POSSIBLY_OFF_TASK), None
            )
            if first_off and days_ago == 1:  # show what a user correction looks like
                repo.set_feedback(
                    first_off.event_id, FocusState.ON_TASK, tr("Looking up reference material")
                )
        ids.append(sid)
    svc.shutdown()
    return ids
