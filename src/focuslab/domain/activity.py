"""Always-on activity recording contracts: probe samples and non-overlapping time spans.

Spans use UTC epoch milliseconds. Time that was not observed (suspend, FocusLab not
running, recording paused) has no span at all, so it is never counted as PC use.
"""

from dataclasses import dataclass
from enum import StrEnum


class SpanKind(StrEnum):
    ACTIVE = "ACTIVE"  # someone is using the PC; the foreground app is attached
    IDLE = "IDLE"  # no keyboard/mouse input for longer than the idle threshold
    LOCKED = "LOCKED"  # workstation locked or the secure desktop is shown


class SystemEvent(StrEnum):
    START = "START"  # recorder started
    STOP = "STOP"  # recorder stopped cleanly
    PAUSE = "PAUSE"  # user paused recording
    RESUME = "RESUME"
    GAP = "GAP"  # the recorder was not scheduled for a while (suspend, freeze)
    CLOCK_CHANGED = "CLOCK_CHANGED"  # wall clock jumped against the monotonic clock
    RECOVERED = "RECOVERED"  # the previous run ended without STOP (crash, kill, power loss)
    # Windows notifications
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    LOGON = "LOGON"
    LOGOFF = "LOGOFF"
    USER_SWITCH_OUT = "USER_SWITCH_OUT"  # console disconnected (fast user switching)
    USER_SWITCH_IN = "USER_SWITCH_IN"
    SUSPEND = "SUSPEND"
    WAKE = "WAKE"
    DISPLAY_OFF = "DISPLAY_OFF"
    DISPLAY_ON = "DISPLAY_ON"
    SESSION_END = "SESSION_END"  # Windows is shutting down, restarting or logging off


@dataclass(frozen=True)
class ForegroundApp:
    """Identity of the foreground program. ``exe_name`` is None when it cannot be read.

    Only the lowercase executable name and the product description are kept; the full
    path (which may contain the user name) and the window title are never stored.
    """

    exe_name: str | None
    display_name: str | None = None


@dataclass(frozen=True)
class ProbeSample:
    app: ForegroundApp | None  # None: no foreground window
    idle_s: float | None
    locked: bool = False


@dataclass(frozen=True)
class ActivitySpan:
    start_ms: int
    end_ms: int
    kind: SpanKind
    exe_name: str | None = None
    display_name: str | None = None
    span_id: int | None = None
    domain: str | None = None  # active tab hostname while a browser is in front, if reported

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms
