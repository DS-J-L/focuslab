import random

import pytest

from focuslab.ui.mascot.behavior_policy import Mood
from focuslab.ui.mascot.director import Director
from focuslab.ui.mascot.petting import PettingGesture
from focuslab.ui.mascot.renderer import RESTING_YAW, facing_yaw


def sweep(gesture, ys, start=0, step=.12, xs=None):
    return [gesture.move(x, y, start + i * step)
            for i, (x, y) in enumerate(zip(xs or [0] * len(ys), ys, strict=True))]


def test_back_and_forth_hover_strokes_are_recognized_at_different_sampling_rates():
    for stride in (2, 5, 10):
        gesture = PettingGesture()
        ys = list(range(0, 41, stride)) + list(range(40, -1, -stride)) + list(range(0, 41, stride))
        assert any(sweep(gesture, ys, step=.01 * stride))


@pytest.mark.parametrize("ys,xs,step", [
    ([0, 10, 20, 30, 40], None, .12),  # one pass
    ([0, 3, -3, 2, -2, 1, -1], None, .12),  # jitter
    ([0, 1, 0, 1, 0, 1, 0], [0, 10, 20, 10, 0, 10, 20], .12),
    ([0, 20, 40, 20, 0, 20, 40], [0, 20, 40, 60, 80, 100, 120], .12),  # diagonal
    ([0, 20, 40, 20, 0, 20, 40], None, .001),  # instantaneous jumps
    ([0, 20, 40, 20, 0, 20, 40], None, 1.0),  # disconnected passes
])
def test_passes_jitter_horizontal_diagonal_teleports_and_long_gaps_are_not_pets(ys, xs, step):
    assert not any(sweep(PettingGesture(), ys, xs=xs, step=step))


def test_reset_does_not_join_two_separate_birds_or_visits():
    gesture = PettingGesture()
    assert not any(sweep(gesture, [0, 20, 40, 20]))
    gesture.reset()
    assert not any(sweep(gesture, [20, 0, 20], start=.5))


@pytest.mark.parametrize("index", range(3))
def test_only_petted_bird_relaxes_then_keeps_a_contented_afterglow(index):
    director = Director(random.Random(3), motion="minimal")
    director.set_motion("normal")
    director._next = [1000.] * 3
    director.set_hover(index, 0)
    director.poses(0)
    director.pet(index, .2)
    poses = [director.poses(.2 + n / 60) for n in range(1, 45)][-1]
    loved = poses[index]
    assert loved.eye_open < .25 and loved.emote == "pet-heart"
    assert abs(loved.head_tilt) > 4
    assert facing_yaw(director.actors[index].plumage.character_id, loved) == pytest.approx(
        RESTING_YAW[director.actors[index].plumage.character_id], abs=.05)
    assert [actor.content(1) for actor in director.actors] == [i == index for i in range(3)]
    director.set_hover(None, 1)
    after = director.poses(5)[index]
    assert abs(after.head_tilt) > 3 and after.emote == "heart"
    assert director.actors[index].content(15)
    normal = director.poses(22)[index]
    assert not director.actors[index].content(22) and normal.eye_open > .9


def test_petting_temporarily_softens_a_reaction_without_changing_the_focus_mood():
    director = Director(random.Random(5), motion="minimal")
    director.set_mood(Mood.WARN, 0)
    director.poses(.1)
    director.pet(1, .2)
    poses = [director.poses(.2 + n / 60) for n in range(1, 50)][-1]
    assert director.mood is Mood.WARN
    assert poses[0].eyes == poses[2].eyes == "angry"
    assert poses[1].eyes == "normal" and poses[1].eye_open < .3
    assert poses[1].emote == "heart"  # reduced motion: a still heart and no head tilt
    assert poses[1].head_tilt == 0 and poses[1].y == 0
    director.poses(23)
    assert director.actors[1].behavior.name == "scold"


def test_flying_bird_cannot_be_petted_on_its_empty_seat():
    director = Director(random.Random(1))
    director.set_away(0, True, 0)
    director.pet(0, .2)
    assert not director.actors[0].content(.3)
