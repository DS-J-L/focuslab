"""Mode-aware state estimation with reason codes, timers and hysteresis.

Principles (DEVELOPMENT_PLAN.md section 5):
- missing or unreliable input -> UNKNOWN, never "distracted";
- looking down alone never triggers POSSIBLY_OFF_TASK;
- short deviations keep the previous state (timers), and returns to ON_TASK or
  UNKNOWN must persist ``enter_dwell_s`` before they take effect.
"""

from dataclasses import dataclass

from focuslab.config import MODE_PROFILES, RULE_VERSION, RuleConfig
from focuslab.domain.models import Decision, FocusState, SessionMode
from focuslab.focus.fusion import AppRelation, FaceEvidence, FusedFrame
from focuslab.focus.reasons import Reason

# (state or None to keep the previous state, confidence, reasons)
Candidate = tuple[FocusState | None, float, tuple[str, ...]]

_FACE_REASON = {
    FaceEvidence.FORWARD: Reason.FACE_FORWARD,
    FaceEvidence.DOWN: Reason.HEAD_DOWN,
    FaceEvidence.AWAY: Reason.HEAD_TURNED_AWAY,
    FaceEvidence.ABSENT: Reason.FACE_NOT_VISIBLE,
}

_ACTIVITY_REASONS = {Reason.ACTIVITY_UNAVAILABLE, Reason.ACTIVITY_STALE}

# Entering these states already waits on a timer, so no extra dwell is needed.
_IMMEDIATE = {FocusState.BREAK, FocusState.POSSIBLY_OFF_TASK, FocusState.AWAY}


@dataclass
class _Timers:
    unrelated_s: float = 0.0
    absent_s: float = 0.0
    head_away_s: float = 0.0


class RuleEngine:
    version = RULE_VERSION

    def __init__(self, mode: SessionMode, cfg: RuleConfig | None = None) -> None:
        self.mode = mode
        self.profile = MODE_PROFILES[mode]
        self.cfg = cfg or RuleConfig()
        self.reset()

    def reset(self) -> None:
        """Forget timers and the current state (after pause, break or an observation gap)."""
        self._timers = _Timers()
        self._current: Decision | None = None
        self._pending: FocusState | None = None
        self._pending_s = 0.0

    @property
    def current(self) -> Decision | None:
        return self._current

    def evaluate(self, frame: FusedFrame, dt_s: float = 1.0) -> Decision:
        self._update_timers(frame, dt_s)
        state, confidence, reasons = self._candidate(frame)
        decision = self._hysteresis(state, confidence, reasons, dt_s)
        self._current = decision
        return decision

    def _update_timers(self, f: FusedFrame, dt: float) -> None:
        t = self._timers
        if f.user_break or f.screen_locked:
            self._timers = _Timers()
            return
        t.unrelated_s = t.unrelated_s + dt if f.app is AppRelation.UNRELATED else 0.0
        t.absent_s = t.absent_s + dt if f.face is FaceEvidence.ABSENT else 0.0
        t.head_away_s = t.head_away_s + dt if f.face is FaceEvidence.AWAY else 0.0

    def _face_reasons(self, f: FusedFrame) -> tuple[str, ...]:
        reason = _FACE_REASON.get(f.face)
        camera = tuple(r for r in f.reasons if r not in _ACTIVITY_REASONS)
        return (reason,) if reason else camera

    def _candidate(self, f: FusedFrame) -> Candidate:
        p, c, t = self.profile, self.cfg, self._timers
        if f.user_break:
            return FocusState.BREAK, 1.0, (Reason.USER_BREAK,)
        if f.screen_locked:
            return FocusState.UNKNOWN, 0.0, (Reason.SCREEN_LOCKED,)

        idle = f.idle_s
        idle_known = idle is not None
        active = idle_known and idle < c.active_idle_s

        # Sustained deviations first.
        if f.app is AppRelation.UNRELATED and t.unrelated_s >= c.unrelated_app_s:
            return FocusState.POSSIBLY_OFF_TASK, 0.7, (Reason.UNRELATED_APP, *self._face_reasons(f))
        if f.face is FaceEvidence.ABSENT and t.absent_s >= p.away_face_absent_s:
            if not idle_known:
                return FocusState.AWAY, 0.5, (Reason.FACE_NOT_VISIBLE, *f.reasons)
            if idle >= c.away_idle_s:
                return FocusState.AWAY, 0.8, (Reason.FACE_NOT_VISIBLE, Reason.USER_IDLE)
        if (
            f.face is FaceEvidence.AWAY
            and t.head_away_s >= p.head_away_s
            and idle_known
            and idle >= c.head_away_idle_s
        ):
            return FocusState.POSSIBLY_OFF_TASK, 0.5, (Reason.HEAD_TURNED_AWAY, Reason.USER_IDLE)

        if f.app is AppRelation.UNRELATED:
            return None, 0.0, (Reason.UNRELATED_APP,)
        if f.app is AppRelation.NEUTRAL:
            return None, 0.0, (Reason.NEUTRAL_APP,)
        if f.app is AppRelation.UNKNOWN:
            reasons = tuple(dict.fromkeys((*f.reasons, *self._face_reasons(f))))
            return FocusState.UNKNOWN, 0.0, reasons

        base: tuple[str, ...] = (Reason.ALLOWED_APP,)
        if f.is_browser and not f.domain:
            base += (Reason.BROWSER_DETAIL_UNKNOWN,)
        if f.face is FaceEvidence.FORWARD:
            return FocusState.ON_TASK, 0.85, (*base, Reason.FACE_FORWARD)
        if f.face is FaceEvidence.DOWN:
            if p.head_down_is_work:
                return FocusState.ON_TASK, 0.8, (*base, Reason.HEAD_DOWN_READING)
            return FocusState.ON_TASK, 0.65, (*base, Reason.HEAD_DOWN)
        if f.face is FaceEvidence.AWAY:
            return None, 0.0, (*base, Reason.HEAD_TURNED_AWAY)
        if f.face is FaceEvidence.ABSENT:
            if active:
                reasons = (*base, Reason.USER_ACTIVE, Reason.FACE_NOT_VISIBLE)
                return FocusState.ON_TASK, 0.55, reasons
            return None, 0.0, (*base, Reason.FACE_NOT_VISIBLE)

        # Camera off or unreliable: PC activity is the only evidence.
        if active:
            return FocusState.ON_TASK, 0.6, (*base, Reason.USER_ACTIVE, *f.reasons)
        if idle_known and p.idle_is_normal:
            return FocusState.ON_TASK, 0.5, (*base, Reason.IDLE_EXPECTED_IN_MODE, *f.reasons)
        if idle_known and idle < c.pc_only_idle_s:
            return None, 0.0, (*base, Reason.USER_IDLE, *f.reasons)
        return FocusState.UNKNOWN, 0.0, (*base, Reason.USER_IDLE, *f.reasons)

    def _hysteresis(
        self, state: FocusState | None, confidence: float, reasons: tuple[str, ...], dt: float
    ) -> Decision:
        current = self._current
        if state is None:
            self._pending, self._pending_s = None, 0.0
            if current is None or current.state is FocusState.BREAK:
                return Decision(FocusState.UNKNOWN, 0.0, (*reasons, Reason.INSUFFICIENT_EVIDENCE))
            return Decision(current.state, current.confidence, (*reasons, Reason.HYSTERESIS_HOLD))
        if (
            current is None
            or state == current.state
            or state in _IMMEDIATE
            or current.state is FocusState.BREAK
        ):
            self._pending, self._pending_s = None, 0.0
            return Decision(state, confidence, reasons)
        self._pending_s = self._pending_s + dt if self._pending == state else dt
        self._pending = state
        if self._pending_s >= self.cfg.enter_dwell_s:
            self._pending, self._pending_s = None, 0.0
            return Decision(state, confidence, reasons)
        return Decision(current.state, current.confidence, (*reasons, Reason.HYSTERESIS_HOLD))

