"""The session reads the browser site and title from the recorder's current span only."""

from focuslab.activity.recorder import RecorderState, RecorderStatus, wall_ms
from focuslab.domain.activity import ActivitySpan, SpanKind
from focuslab.ui.context import BROWSER_DETAIL_TTL_MS, AppContext


class FakeRecorder:
    def __init__(self, span):
        self.span = span
        self.title_tracking = None

    def status(self):
        return RecorderStatus(RecorderState.RUNNING, self.span)

    def set_title_tracking(self, on):
        self.title_tracking = on


def span(end_ms, exe="chrome.exe"):
    return ActivitySpan(
        end_ms - 5_000, end_ms, SpanKind.ACTIVE, exe, None, None, "youtube.com",
        page_title="Unity AR Foundation Tutorial",
    )


def make_context(recorder):
    ctx = AppContext(demo=False)
    ctx.set_flag("consent.browser", True)
    ctx.set_flag("consent.page_titles", True)
    ctx.recorder = recorder
    return ctx


def test_current_browser_detail_comes_with_its_title():
    ctx = make_context(FakeRecorder(span(wall_ms())))
    try:
        assert ctx._current_browser("chrome.exe") == ("youtube.com", "Unity AR Foundation Tutorial")
        assert ctx._current_browser("msedge.exe") == (None, None)  # another program in front
    finally:
        ctx.service.shutdown()


def test_stale_browser_detail_is_unknown():
    ctx = make_context(FakeRecorder(span(wall_ms() - BROWSER_DETAIL_TTL_MS - 1_000)))
    try:
        assert ctx._current_browser("chrome.exe") == (None, None)
    finally:
        ctx.service.shutdown()


def test_withdrawing_title_consent_stops_title_use_on_the_next_tick():
    recorder = FakeRecorder(span(wall_ms()))
    ctx = make_context(recorder)
    try:
        ctx.set_page_titles_consent(False)
        assert recorder.title_tracking is False
        # Even a span the recorder has not scrubbed yet no longer yields its title.
        assert ctx._current_browser("chrome.exe") == ("youtube.com", None)
    finally:
        ctx.service.shutdown()
