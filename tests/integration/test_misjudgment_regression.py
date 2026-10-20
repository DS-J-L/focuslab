"""UX-01 regression: a lecture session with note-taking and AI questions.

Reproduces the reported "증강현실 공부 조금" session: lecture mode with the default allow
list, Chrome without the browser extension, then Notepad and Claude, which are not on the
allow list. Notepad or Claude alone must not establish deviation, and facing the camera
must not establish task work either. An obvious game still does.
"""

import pytest

from focuslab.config import DEFAULT_ALLOWED_APPS
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.focus.reasons import Reason
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.services.session_service import SessionService

# (seconds, process, input) -- Notepad for 5 min 34 s, as in the reported session
SCRIPT = (
    (120, "chrome.exe", "idle"),
    (334, "notepad.exe", "active"),
    (60, "chrome.exe", "idle"),
    (120, "claude.exe", "active"),
    (60, "chrome.exe", "idle"),
    (60, "leagueclient.exe", "active"),
)


def _phases():
    start = 0
    for seconds, name, _ in SCRIPT:
        yield name, start, start + seconds
        start += seconds


def run_session(tmp_path, clock, camera):
    svc = SessionService(
        tmp_path / "s.db",
        face_factory=lambda cfg: MockFaceSource(((3600, "forward"),), clock),
        activity_factory=lambda cfg: MockActivitySource(cfg.allowed_apps, SCRIPT, loop=False),
        clock=clock,
        auto_tick=False,
    )
    allowed = DEFAULT_ALLOWED_APPS[SessionMode.LECTURE]
    assert "notepad.exe" not in allowed and "claude.exe" not in allowed
    svc.start(SessionConfig("증강현실 공부 조금", SessionMode.LECTURE, 0, allowed, camera))
    decisions = []
    for _ in range(sum(s[0] for s in SCRIPT)):
        clock.advance(1)
        decisions.append(svc.tick())
    svc.shutdown()
    return decisions


@pytest.mark.parametrize("camera", [False, True])
def test_notes_and_ai_questions_are_not_deviation(tmp_path, clock, camera):
    decisions = run_session(tmp_path, clock, camera)
    by_app = {}
    for name, start, end in _phases():
        by_app.setdefault(name, []).extend(decisions[start:end])

    for name, hint in (
        ("notepad.exe", Reason.NOTE_TAKING_POSSIBLE),
        ("claude.exe", Reason.AI_ASSISTANT_POSSIBLE),
    ):
        states = {d.state for d in by_app[name]}
        assert FocusState.POSSIBLY_OFF_TASK not in states, name
        # neither the app name nor a forward-facing camera confirms the task
        assert by_app[name][-1].state is FocusState.UNKNOWN
        assert hint in by_app[name][-1].reason_codes

    # Chrome without the extension may show any site: unknown, not task work
    assert FocusState.ON_TASK not in {d.state for d in by_app["chrome.exe"]}
    assert Reason.BROWSER_DETAIL_UNKNOWN in by_app["chrome.exe"][-1].reason_codes

    assert by_app["leagueclient.exe"][-1].state is FocusState.POSSIBLY_OFF_TASK
