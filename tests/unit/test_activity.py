import sys

import pytest

from focuslab.activity.windows_tracker import WindowsActivitySource, allowed_status
from focuslab.mock_sources import MockActivitySource


def test_allowed_status_is_case_insensitive_and_neutral_aware():
    allowed = ("Code.exe", "chrome.exe")
    assert allowed_status("code.EXE", allowed) is True
    assert allowed_status("game.exe", allowed) is False
    assert allowed_status("explorer.exe", allowed) is None
    assert allowed_status("focuslab", allowed) is None
    assert allowed_status(None, allowed) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API")
def test_windows_source_reports_process_name_and_idle_only():
    obs = WindowsActivitySource(("code.exe",)).sample(123)
    assert obs.available and obs.timestamp_ms == 123
    assert obs.idle_seconds is not None and obs.idle_seconds >= 0
    assert set(vars(obs)) == {
        "timestamp_ms", "process_name", "is_allowed_app", "idle_seconds", "available",
        "screen_locked", "domain", "page_title",  # from the browser extension only
    }
    assert obs.domain is None and obs.page_title is None  # no recorder, no site


def test_mock_activity_script_plays_in_order():
    src = MockActivitySource(
        ("code.exe",), [(2, "code.exe", "active"), (3, "game.exe", "idle")], loop=False
    )
    obs = [src.sample(t * 1000) for t in range(6)]
    assert [o.process_name for o in obs] == ["code.exe"] * 2 + ["game.exe"] * 4
    assert [o.is_allowed_app for o in obs[:3]] == [True, True, False]
    assert obs[3].idle_seconds == 1.0


def test_site_entries_restrict_browsers_only_when_the_site_is_known():
    allowed = ("code.exe", "chrome.exe", "github.com")
    assert allowed_status("chrome.exe", allowed, "github.com") is True
    assert allowed_status("chrome.exe", allowed, "gist.github.com") is True
    assert allowed_status("chrome.exe", allowed, "youtube.com") is False
    assert allowed_status("chrome.exe", allowed, None) is True  # no extension: as before
    assert allowed_status("msedge.exe", ("code.exe", "github.com"), "github.com") is True
    assert allowed_status("chrome.exe", ("code.exe", "chrome.exe"), "youtube.com") is True
    assert allowed_status("code.exe", allowed, "github.com") is True


def test_known_site_removes_the_browser_detail_unknown_reason():
    from focuslab.domain.models import ActivityObservation, SessionMode
    from focuslab.focus.fusion import fuse
    from focuslab.focus.reasons import Reason
    from focuslab.focus.rules import RuleEngine

    def decide(domain):
        obs = ActivityObservation(0, "chrome.exe", True, 1.0, True, domain=domain)
        frame = fuse(0, None, obs, camera_enabled=False)
        return RuleEngine(SessionMode.CODING).evaluate(frame).reason_codes

    assert Reason.BROWSER_DETAIL_UNKNOWN in decide(None)
    assert Reason.BROWSER_DETAIL_UNKNOWN not in decide("github.com")
