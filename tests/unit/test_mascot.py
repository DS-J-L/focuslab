"""Parrot poses and behaviors: data, scheduling, personalities, interactions, pointer."""

import random
from collections import Counter

import pytest

from focuslab.ui.mascot.animation import Pose, blend, load_behaviors, parse_behaviors
from focuslab.ui.mascot.director import BREAK, FINISH, MOTION, PAUSE, WINDOW, Director


def frames(director, start, seconds, fps=30):
    t = start
    poses = []
    while t < start + seconds:
        poses.append(director.poses(t))
        t += 1 / fps
    return poses


def test_blend_interpolates_numbers_and_switches_discrete_values_halfway():
    a, b = Pose(), Pose(y=-10, eyes="happy", emote="note")
    assert blend(a, b, 0) == a and blend(a, b, 1) == b
    quarter = blend(a, b, 0.25)
    assert quarter.y == -2.5 and quarter.eyes == "normal" and quarter.emote is None
    assert blend(a, b, 0.75).eyes == "happy"


def test_parrots_breathe_out_of_step_and_blink_now_and_then():
    director = Director(random.Random(1), motion="minimal")
    poses = frames(director, 0.0, 12)
    for i in range(3):
        squash = [p[i].squash for p in poses]
        assert max(squash) - min(squash) > 0.02  # breathing
        assert min(p[i].eye_open for p in poses) < 0.3  # blinked
        assert sum(p[i].eye_open >= 0.99 for p in poses) > len(poses) * 0.8  # mostly open
    first = [p[0].squash for p in poses[:30]]
    second = [p[1].squash for p in poses[:30]]
    assert first != second


def test_pointed_at_parrot_perks_up_and_the_others_look_at_it():
    director = Director(random.Random(2), motion="minimal")
    director.set_hover(FINISH, 0.0)
    red, blue, yellow = frames(director, 0.0, 1)[-1]
    assert blue.scale > 1.05 and blue.eyes == "wide" and blue.y < 0
    assert red.turn > 0.5 and yellow.turn < -0.5  # both glance at the middle one

    director.set_hover(None, 1.0)
    calm = frames(director, 1.0, 1.5)[-1]
    assert all(abs(p.turn) < 0.05 and p.scale < 1.01 for p in calm)


def test_window_buttons_make_everyone_peek_and_the_nearest_one_wonder():
    director = Director(random.Random(3), motion="minimal")
    director.set_hover(WINDOW, 0.0)
    poses = frames(director, 0.0, 1)[-1]
    assert all(p.look_y < -0.5 for p in poses)
    assert poses[BREAK].emote == "dots"
    assert poses[PAUSE].emote is None and poses[FINISH].emote is None


# Behaviors ---------------------------------------------------------------------------
def test_shipped_behaviors_load_and_start_and_end_at_rest():
    behaviors = load_behaviors()
    assert {"doze", "sing", "head_turn", "stretch", "yawn", "preen", "lean", "startle"} <= set(
        behaviors
    )
    for b in behaviors.values():
        if b.loop:
            continue
        # Random ones begin from rest too; "land" begins in the air, coming from a flight.
        for t in (0.0, b.duration) if b.random else (b.duration,):
            pose = b.sample(t)
            for channel in ("x", "y", "tilt", "turn", "head_tilt", "wing_l", "wing_r", "beak_open"):
                assert abs(getattr(pose, channel)) < 0.5, (b.name, t, channel)
            assert abs(pose.squash - 1) < 0.02 and pose.eye_open > 0.95, b.name


def test_behavior_data_typos_fail_loudly():
    with pytest.raises(ValueError, match="unknown pose channels"):
        parse_behaviors({"behaviors": {"x": {"duration": 1, "tracks": {"wingz": [[0, 0]]}}}})
    with pytest.raises(ValueError, match="key times"):
        backwards = {"y": [[0.5, 0], [0.2, 1]]}
        parse_behaviors({"behaviors": {"x": {"duration": 1, "tracks": backwards}}})


def test_aimed_behaviors_mirror_towards_the_other_side():
    lean = load_behaviors()["lean"]
    right, left = lean.sample(lean.duration / 2, 1), lean.sample(lean.duration / 2, -1)
    assert right.tilt > 5 and left.tilt == -right.tilt and left.x == -right.x
    assert right.emote == "heart"


def started(director, seconds, fps=10):
    """(time, parrot index, behavior name) for each behavior a director starts."""
    seen, current = [], [None] * 3
    t = 0.0
    while t < seconds:
        director.poses(t)
        for i, actor in enumerate(director.actors):
            name = actor.behavior.name if actor.behavior else None
            if name and name != current[i]:
                seen.append((t, i, name))
            current[i] = name
        t += 1 / fps
    return seen


def test_each_parrot_follows_its_personality_and_rests_between_behaviors():
    seen = started(Director(random.Random(4)), 1800)
    counts = [Counter(name for _, i, name in seen if i == k) for k in range(3)]
    assert counts[0]["doze"] > counts[0]["sing"]  # red dozes
    assert counts[1]["stare"] + counts[1]["preen"] > counts[1]["sing"]  # blue stares and preens
    assert counts[2]["sing"] > counts[2]["doze"]  # yellow sings
    assert counts[1]["dance"] == 0  # blue never dances
    for k in range(3):
        starts = [t for t, i, _ in seen if i == k]
        assert 1800 / 40 < len(starts) < 1800 / 7  # busy, but never nonstop


def test_cooldowns_keep_a_behavior_from_repeating_right_away():
    director = Director(random.Random(5), motion="lively")
    seen = started(director, 1200)
    last: dict[tuple[int, str], float] = {}
    for t, i, name in seen:
        if (i, name) in last:
            assert t - last[(i, name)] >= director.behaviors[name].cooldown - 0.11
        last[(i, name)] = t


def test_pairs_lean_on_each_other_and_others_watch_a_performance():
    director = Director(random.Random(6), motion="lively")
    seen = started(director, 1200)
    leans = [(t, i) for t, i, name in seen if name == "lean"]
    assert leans
    t, i = leans[0]
    partners = {j for tt, j in leans if tt == t}
    assert len(partners) == 2 and max(partners) - min(partners) == 1  # neighbours

    director = Director(random.Random(7), behaviors=load_behaviors(), motion="lively")
    director.motion = MOTION["lively"].__class__((1.0, 1.0), 1.0, 0.0)  # always watched
    director.actors[1].play(director.behaviors["sing"], 0.0)
    director._next = [1e9, 1e9, 1e9]
    director._start(1, director.behaviors["sing"], 0.0)
    poses = frames(director, 0.0, 1)[-1]
    assert poses[0].turn > 0.3 and poses[2].turn < -0.3  # both look at the singer


def test_minimal_movement_only_breathes_and_blinks():
    director = Director(random.Random(8), motion="minimal")
    assert started(director, 600) == []
    director.set_motion("normal")
    assert started(director, 120)
