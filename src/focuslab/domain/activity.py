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


class Category(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STUDY = "STUDY"
    DOCUMENTATION = "DOCUMENTATION"
    RESEARCH = "RESEARCH"
    COMMUNICATION = "COMMUNICATION"
    ENTERTAINMENT = "ENTERTAINMENT"
    GAMING = "GAMING"
    PRODUCTIVITY = "PRODUCTIVITY"
    BREAK = "BREAK"
    UNKNOWN = "UNKNOWN"


class ClassSource(StrEnum):
    RULE = "rule"  # built-in rule
    USER_RULE = "user_rule"  # rule the user created from a correction
    USER = "user"  # the user corrected this span
    SYSTEM = "system"  # observed state (idle, locked)


class ClassReason(StrEnum):
    APP_RULE = "APP_RULE"
    SITE_RULE = "SITE_RULE"
    GAME_LIBRARY = "GAME_LIBRARY"
    AMBIGUOUS_APP = "AMBIGUOUS_APP"
    AMBIGUOUS_SITE = "AMBIGUOUS_SITE"
    BROWSER_NO_SITE = "BROWSER_NO_SITE"
    NEUTRAL_SHELL = "NEUTRAL_SHELL"
    UNREADABLE_APP = "UNREADABLE_APP"
    NO_RULE = "NO_RULE"
    IDLE = "IDLE"
    LOCKED = "LOCKED"
    USER_APP_RULE = "USER_APP_RULE"
    USER_SITE_RULE = "USER_SITE_RULE"
    USER_CORRECTION = "USER_CORRECTION"
    EXCLUDED = "EXCLUDED"


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
    game_library: bool = False  # path under a Steam/Epic/Riot/Xbox games folder (not stored)


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
    # classification stored when the span was recorded (None for rows from before v4)
    category: Category | None = None
    confidence: float | None = None
    reason: ClassReason | None = None
    source: ClassSource | None = None
    excluded: bool = False  # the program or site is on the user's exclusion list
    user_category: Category | None = None  # the user's correction of this span

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms
