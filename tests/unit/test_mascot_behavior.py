"""Focus state to parrot mood: thresholds, resets, and nothing scolding on uncertain states."""

import random

import pytest

from focuslab.domain.models import Decision, FocusState
from focuslab.services.session_service import Lifecycle, LiveSnapshot
from focuslab.ui.mascot.behavior_policy import BehaviorPolicy, Mood
from focuslab.ui.mascot.director import MOOD_LOOPS, Director


def snap(state=FocusState.ON_TASK, lifecycle=Lifecycle.RUNNING, on_break=False):
    return LiveSnapshot(lifecycle=lifecycle, on_break=on_break, decision=Decision(state, 0.8))


def run(policy, state, start, seconds, **kw):
    t, mood = start, None
    while t <= start + seconds:
        mood = policy.update(snap(state, **kw), t)
        t += 0.5
    return mood, t


def test_off_task_is_noticed_then_scolded_then_alarming():
    policy = BehaviorPolicy()
    assert policy.update(snap(), 0) is Mood.CALM
    assert policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 1) is Mood.WATCH
    assert policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 30.5) is Mood.WATCH
    assert policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 31) is Mood.WARN
    assert policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 61) is Mood.ALARM
    assert policy.off_task_s(61) == 60
    # Back to work: a short cheer, then calm.
    assert policy.update(snap(), 62) is Mood.CHEER
    assert policy.update(snap(), 64) is Mood.CHEER
    assert policy.update(snap(), 65) is Mood.CALM
    assert policy.off_task_s(65) == 0


def test_a_short_glance_away_never_turns_into_a_scolding_and_needs_no_cheer():
    policy = BehaviorPolicy()
    policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 0)
    assert policy.update(snap(), 10) is Mood.CALM  # only watched, nothing to cheer about
    assert run(policy, FocusState.POSSIBLY_OFF_TASK, 11, 29)[0] is Mood.WATCH  # timer restarted


@pytest.mark.parametrize(
    "interruption, mood",
    [
        (dict(state=FocusState.UNKNOWN), Mood.CALM),
        (dict(state=FocusState.AWAY), Mood.AWAY),
        (dict(state=FocusState.BREAK), Mood.BREAK),
        (dict(on_break=True), Mood.BREAK),
        (dict(lifecycle=Lifecycle.PAUSED), Mood.PAUSED),
    ],
)
def test_uncertain_away_break_and_pause_never_scold_and_reset_the_timer(interruption, mood):
    policy = BehaviorPolicy()
    run(policy, FocusState.POSSIBLY_OFF_TASK, 0, 50)
    kw = dict(interruption)
    state = kw.pop("state", FocusState.POSSIBLY_OFF_TASK)
    # Even if the estimate still says off task underneath a break or pause.
    assert policy.update(snap(state, **kw), 51) is mood
    assert policy.off_task_s(51) == 0
    assert policy.update(snap(FocusState.POSSIBLY_OFF_TASK), 52) is Mood.WATCH


def test_reactions_can_be_turned_off():
    policy = BehaviorPolicy(reactions=False)
    assert run(policy, FocusState.POSSIBLY_OFF_TASK, 0, 120)[0] is Mood.CALM
    assert policy.update(snap(lifecycle=Lifecycle.PAUSED), 121) is Mood.PAUSED


def test_moods_replace_idle_behaviors_with_their_reaction_loops():
    director = Director(random.Random(1))
    director.set_mood(Mood.WARN, 0.0)
    poses = [director.poses(t / 30) for t in range(90)][-1]
    assert [a.behavior.name for a in director.actors] == list(MOOD_LOOPS[Mood.WARN])
    assert all(p.eyes == "angry" and p.emote == "anger" for p in poses)

    director.set_mood(Mood.PAUSED, 3.0)
    poses = [director.poses(3 + t / 30) for t in range(30)][-1]
    assert all(p.eye_open < 0.3 and p.emote == "zzz" for p in poses)

    director.set_mood(Mood.CHEER, 4.0)
    poses = [director.poses(4 + t / 30) for t in range(30)][-1]
    assert all(p.eyes == "happy" for p in poses)

    director.set_mood(Mood.CALM, 7.0)  # cheering ended: back to their own behaviors
    assert any(name == "sing" for name in started_names(director, 7.0, 300))


def started_names(director, start, seconds):
    names = set()
    t = start
    while t < start + seconds:
        director.poses(t)
        names |= {a.behavior.name for a in director.actors if a.behavior}
        t += 0.1
    return names


def test_a_break_starts_with_yellow_singing():
    director = Director(random.Random(2))
    director.set_mood(Mood.BREAK, 0.0)
    assert director.actors[2].behavior.name == "sing"


def test_minimal_movement_still_shows_reactions_but_holds_them_still():
    director = Director(random.Random(3), motion="minimal")
    director.set_mood(Mood.ALARM, 0.0)
    poses = [director.poses(t / 30) for t in range(60)]
    assert all(p[0].eyes == "angry" for p in poses[1:])
    ys = [p[0].y for p in poses[1:]]
    assert max(ys) == min(ys)  # no stomping


def test_hovering_during_a_reaction_resumes_it_afterwards():
    director = Director(random.Random(4))
    director.set_mood(Mood.WARN, 0.0)
    director.poses(0.1)
    director.set_hover(0, 0.2)
    director.poses(0.3)
    assert director.actors[0].behavior is None  # paying attention to the pointer
    director.set_hover(None, 0.4)
    director.poses(0.5)
    assert director.actors[0].behavior.name == "scold"
