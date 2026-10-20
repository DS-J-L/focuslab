"""From the session's estimated focus state to the parrots' mood.

Off-task is an estimate, so the parrots never scold on a hunch: they only notice at
first, get cross after ``warn_after`` seconds of uninterrupted ``POSSIBLY_OFF_TASK``
and alarmed after ``alarm_after``. These timers are separate from the rule engine's own
delays. Anything uncertain (``UNKNOWN``), being away, a break or a pause resets them.
"""

from enum import StrEnum

from focuslab.domain.models import FocusState
from focuslab.services.session_service import Lifecycle, LiveSnapshot

WARN_AFTER_S = 30.0
ALARM_AFTER_S = 60.0
CHEER_S = 2.5


class Mood(StrEnum):
    CALM = "calm"  # their own idle behaviors
    WATCH = "watch"  # off task: they stop and look at you
    WARN = "warn"  # off task for warn_after: cross, flapping a little
    ALARM = "alarm"  # off task for alarm_after: angry (and, if enabled, flying)
    CHEER = "cheer"  # back on task after a warning
    PAUSED = "paused"  # asleep
    BREAK = "break"  # relaxed
    AWAY = "away"  # quietly waiting for you to come back


class BehaviorPolicy:
    def __init__(
        self,
        warn_after: float = WARN_AFTER_S,
        alarm_after: float = ALARM_AFTER_S,
        reactions: bool = True,
    ) -> None:
        self.warn_after = warn_after
        self.alarm_after = alarm_after
        self.reactions = reactions  # False: never react to estimated off-task time
        self.mood = Mood.CALM
        self._off_since: float | None = None
        self._cheer_until = 0.0

    def off_task_s(self, now: float) -> float:
        "How long the session has been estimated off task without interruption."
        return 0.0 if self._off_since is None else now - self._off_since

    def update(self, snap: LiveSnapshot, now: float) -> Mood:
        self.mood = self._decide(snap, now)
        return self.mood

    def _decide(self, snap: LiveSnapshot, now: float) -> Mood:
        if snap.lifecycle is Lifecycle.PAUSED:
            return self._reset(Mood.PAUSED)
        if snap.lifecycle is not Lifecycle.RUNNING:
            return self._reset(Mood.CALM)
        state = snap.decision.state if snap.decision else FocusState.UNKNOWN
        if snap.on_break or state is FocusState.BREAK:
            return self._reset(Mood.BREAK)
        if state is FocusState.AWAY:
            return self._reset(Mood.AWAY)
        if state is FocusState.POSSIBLY_OFF_TASK and self.reactions:
            if self._off_since is None:
                self._off_since = now
            off = now - self._off_since
            if off >= self.alarm_after:
                return Mood.ALARM
            return Mood.WARN if off >= self.warn_after else Mood.WATCH
        if state is FocusState.ON_TASK and self.mood in (Mood.WARN, Mood.ALARM):
            self._cheer_until = now + CHEER_S  # pleased you are back
        self._off_since = None
        return Mood.CHEER if now < self._cheer_until else Mood.CALM

    def _reset(self, mood: Mood) -> Mood:
        self._off_since = None
        self._cheer_until = 0.0
        return mood
