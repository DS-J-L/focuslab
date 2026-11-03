"One parrot: the behavior it is playing, breathing, blinking, and reactions to the pointer."

import math
import random
from dataclasses import dataclass, replace

from focuslab.ui.mascot.animation import NEUTRAL, Behavior, Pose, approach, blend, ease_in_out
from focuslab.ui.mascot.renderer import RESTING_YAW, Plumage

BLINK_S = 0.18
HOVER_S = 0.12  # time constant for perking up and settling down
TRANSITION_S = 0.18
CONTENT_S = 20.0


@dataclass(frozen=True)
class Attention:
    """Where a parrot's attention is. ``toward`` is -1 (left) .. 1 (right)."""

    hovered: bool = False  # the pointer is on this parrot
    toward: float = 0.0  # glance sideways at something
    up: bool = False  # look up (at the window buttons)
    emote: str | None = None


CALM = Attention()


class BirdActor:
    def __init__(self, name: str, plumage: Plumage, rng: random.Random) -> None:
        self.name = name
        self.plumage = plumage
        self._rest_yaw = RESTING_YAW[plumage.character_id]
        self.rng = rng
        self._gaze_rng = random.Random(rng.getrandbits(64))
        self.idle_gaze = True
        self._gaze_at: float | None = None
        self._gaze_target = (0.0, 0.0)
        self._gaze_x = self._gaze_y = 0.0
        self.attention = CALM
        self._phase = rng.uniform(0, math.tau)  # so the three never breathe in step
        self._next_blink: float | None = None
        self._last: float | None = None
        self._perk = 0.0  # smoothed 0..1 hover amount
        self._glance = 0.0  # smoothed toward
        self._up = 0.0
        self._emote_since = 0.0
        self.resting = True
        self.behavior: Behavior | None = None
        self._started = 0.0
        self._side = 1
        self._still = False
        self._watch = 0.0  # direction of a neighbour being watched, until _watch_until
        self._watch_until = 0.0
        self._last_base = NEUTRAL
        self._transition_from = NEUTRAL
        self._returning = False
        self._petted_at: float | None = None
        self._pet_burst_at = 0.0
        self._affection = 0.0
        self.reduced_motion = False

    # behaviors ----------------------------------------------------------------------
    def play(self, behavior: Behavior, now: float, side: int = 1, still: bool = False) -> None:
        "Start ``behavior`` at ``now``; ``still`` holds its expression without moving."
        self._transition_from = self._last_base
        self._returning = False
        self.behavior, self._started, self._side = behavior, now, side
        self._still = still

    def stop(self) -> None:
        self._transition_from = self._last_base
        self._started = self._last if self._last is not None else 0.0
        self._returning = True
        self.behavior = None

    def busy(self, now: float) -> bool:
        b = self.behavior
        if b is not None and not b.loop and now - self._started >= b.duration:
            self.behavior = None
        return self.behavior is not None

    def watch(self, toward: float, until: float) -> None:
        "Turn to look at a neighbour doing something (``toward`` -1 left, 1 right)."
        self._watch, self._watch_until = toward, until

    def attend(self, attention: Attention, now: float) -> None:
        if attention.emote != self.attention.emote:
            self._emote_since = now
        self.attention = attention

    def pet(self, now: float, still: bool = False) -> None:
        "Enjoy an intentional stroke, then keep a little contentment after the hand leaves."
        if self._petted_at is None or now - self._petted_at > 1.0:
            self._pet_burst_at = now
            self.stop()
        self._petted_at = now
        self.reduced_motion = still

    def content(self, now: float) -> bool:
        return self._petted_at is not None and now - self._petted_at < CONTENT_S

    def pose(self, now: float) -> Pose:
        dt = 0.0 if self._last is None else now - self._last
        self._last = now
        base = NEUTRAL
        if self.busy(now):
            t = self.behavior.duration * 0.25 if self._still else now - self._started
            target = self.behavior.sample(max(0.0, t), self._side)
            u = ease_in_out((now - self._started) / TRANSITION_S)
            base = target if self._still else blend(self._transition_from, target, u)
        elif self._returning:
            u = ease_in_out((now - self._started) / TRANSITION_S)
            base = blend(self._transition_from, NEUTRAL, u)
            if u >= 1:
                self._returning = False
        self._last_base = base
        a = self.attention
        toward = a.toward
        if a == CALM and now < self._watch_until:
            toward = self._watch
        perk, up = (1.0 if a.hovered else 0.0), (1.0 if a.up else 0.0)
        self._perk = approach(self._perk, perk, dt, HOVER_S)
        self._glance = approach(self._glance, toward, dt, HOVER_S * 2.5)
        self._up = approach(self._up, up, dt, HOVER_S * 1.5)
        gaze_moving = self._idle_look(now, dt, self.behavior is None and a == CALM
                                      and now >= self._watch_until and not self._returning
                                      and not self.content(now))
        # Only breathing and blinking: the view can then draw fewer frames.
        self.resting = (
            self.behavior is None
            and not self._returning
            and a.emote is None
            and not gaze_moving
            and max(abs(self._perk - perk), abs(self._glance - toward), abs(self._up - up)) < 0.01
        )

        breath = math.sin(now * math.tau / 3.4 + self._phase)
        pose = replace(
            base,
            squash=base.squash * (1 + 0.012 * breath),
            crest=base.crest + 3 * math.sin((now - 0.055) * math.tau / 5.0 + self._phase),
            eye_open=base.eye_open * self._blink(now),
            turn=base.turn + self._gaze_x,
            look_x=base.look_x + self._gaze_x,
            look_y=base.look_y + self._gaze_y,
        )
        if self._glance or self._up:
            # Attention uses a world direction, independent of the resting angle.
            bias = self._rest_yaw * min(1, abs(self._glance))
            pose = replace(
                pose,
                turn=pose.turn + 0.7 * self._glance - bias,
                look_x=pose.look_x + self._glance + 0.4 * self._up - bias,
                look_y=pose.look_y - self._up,
                tilt=pose.tilt + 4 * self._glance,
            )
        if self._perk > 0.01:
            perked = replace(
                pose,
                y=pose.y - 4,
                scale=pose.scale * 1.08,
                eyes="wide",
                eye_open=max(pose.eye_open, 1.0),
                wing_l=pose.wing_l + 18,
                wing_r=pose.wing_r + 18,
                crest=pose.crest + 8,
            )
            pose = blend(pose, perked, self._perk)
        if a.emote:
            pose = replace(pose, emote=a.emote, emote_t=now - self._emote_since)
        pose = self._enjoy_pet(pose, now, dt)
        return pose

    def _enjoy_pet(self, pose: Pose, now: float, dt: float) -> Pose:
        if self._petted_at is None:
            return pose
        age = max(0.0, now - self._petted_at)
        target = 1 - ease_in_out((age - 12) / (CONTENT_S - 12))
        self._affection = approach(self._affection, target, dt, .18)
        love = self._affection
        if love < .005 and not self.content(now):
            self._petted_at = None
            self._affection = 0.0
            return pose
        contact = 1 - ease_in_out((age - .45) / .8)
        phase = (age - 1.25) % 4.8
        smile = (ease_in_out(phase / .1) * (1 - ease_in_out((phase - .45) / .13))
                 if age > 1.25 and not self.reduced_motion else 0.0)
        openness = .12 if contact > .4 else .95 - .8 * smile
        # Preserve the authored side view: "happy" currently selects a frontal face.
        # Closed and half-closed eyes are available in every directional image rig.
        pleased = replace(
            pose, eyes="normal", eye_open=pose.eye_open * openness,
            scale=1.0, y=0.0, wing_l=0.0, wing_r=0.0,
            turn=0.0, look_x=0.0, look_y=-.1, puff=.18, emote=None,
        )
        if not self.reduced_motion:
            side = -1 if self.name == "blue" else 1
            nuzzle = 1.2 * contact * math.sin((now - self._pet_burst_at) * math.tau * 1.3)
            pleased = replace(pleased, head_tilt=side * (4 + 4 * contact) + nuzzle,
                              squash=pose.squash * (1 - .015 * contact))
        burst = now - self._pet_burst_at
        if 0 <= burst < 2.2:
            pleased = replace(pleased, emote="heart" if self.reduced_motion else "pet-heart",
                              emote_t=0.0 if self.reduced_motion else burst)
        elif age < 6:
            pleased = replace(pleased, emote="heart", emote_t=0.0)
        self.resting = (self.resting and abs(love - target) < .01
                        and (burst >= 2.2 or self.reduced_motion)
                        and not (age > 1.25 and phase < .65 and not self.reduced_motion))
        return blend(pose, pleased, love)

    def _idle_look(self, now: float, dt: float, available: bool) -> bool:
        """Independent dwell times and directions; never a left/right metronome."""
        if available and self.idle_gaze:
            if self._gaze_at is None:
                self._gaze_at = now + self._gaze_rng.uniform(2.5, 6.5)
            elif now >= self._gaze_at:
                choices = [((0., 0.), 4), ((0., -.9), 1), ((0., .8), 1)]
                for yaw, weight in ((-.5, 3), (.5, 3), (-1., 1), (1., 1)):
                    if abs(yaw - self._rest_yaw) > .01:
                        choices.append(((yaw - self._rest_yaw, 0.), weight))
                candidates = [(p, w) for p, w in choices if p != self._gaze_target]
                self._gaze_target = self._gaze_rng.choices(
                    [p for p, _ in candidates], [w for _, w in candidates])[0]
                self._gaze_at = now + self._gaze_rng.uniform(3.0, 7.5)
                # A blink often accompanies a larger change in attention.
                if abs(self._gaze_target[0] - self._gaze_x) > .6:
                    self._next_blink = now
            target = self._gaze_target
        else:
            self._gaze_at = None
            self._gaze_target = target = (0., 0.)
        self._gaze_x = approach(self._gaze_x, target[0], dt, .18)
        self._gaze_y = approach(self._gaze_y, target[1], dt, .22)
        return max(abs(self._gaze_x - target[0]), abs(self._gaze_y - target[1])) > .01

    def _blink(self, now: float) -> float:
        if self._next_blink is None:
            self._next_blink = now + self.rng.uniform(0.8, 4.0)
        if now < self._next_blink:
            if self._next_blink - now < 0.034:
                self.resting = False  # wake before the first eyelid frame
            return 1.0
        t = now - self._next_blink
        if t >= BLINK_S:
            # Now and then a quick double blink.
            gap = 0.25 if self.rng.random() < 0.15 else self.rng.uniform(2.5, 6.0)
            self._next_blink = now + gap
            return 1.0
        self.resting = False
        if t < 0.068:
            return 1.0 - ease_in_out(t / 0.068)
        if t < 0.100:
            return 0.0
        return ease_in_out((t - 0.100) / (BLINK_S - 0.100))
