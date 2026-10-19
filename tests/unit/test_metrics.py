from focuslab.domain.events import StateSegment, build_segments
from focuslab.domain.models import FocusState, StateSample
from focuslab.focus.metrics import apply_corrections, compute_metrics, format_duration

ON, OFF, AWAY, BREAK, UNKNOWN = (
    FocusState.ON_TASK,
    FocusState.POSSIBLY_OFF_TASK,
    FocusState.AWAY,
    FocusState.BREAK,
    FocusState.UNKNOWN,
)


def samples(*runs):
    """runs of (state, seconds[, app])"""
    out, t = [], 0
    for run in runs:
        state, n = run[0], run[1]
        app = run[2] if len(run) > 2 else None
        for _ in range(n):
            out.append(StateSample(t, state, 1.0, (), app))
            t += 1
    return out


def test_build_segments_merges_runs_and_splits_gaps():
    s = samples((ON, 3, "code.exe"), (OFF, 2, "game.exe"), (ON, 1, "code.exe"))
    segs = build_segments(s)
    assert [(g.state, g.start_s, g.end_s) for g in segs] == [(ON, 0, 3), (OFF, 3, 5), (ON, 5, 6)]
    assert segs[1].app_names == ("game.exe",)
    gap = [StateSample(0, ON, 1.0), StateSample(5, ON, 1.0)]
    assert len(build_segments(gap)) == 2


def test_state_totals_ratio_and_coverage():
    m = compute_metrics(samples((ON, 60), (OFF, 20), (AWAY, 10), (BREAK, 30), (UNKNOWN, 10)))
    assert m.measured_s == 130
    assert m.seconds[ON] == 60 and m.seconds[BREAK] == 30
    assert m.on_task_ratio == 60 / 80
    assert m.coverage == (100 - 10) / 100


def test_ratio_is_unmeasurable_without_on_or_off():
    m = compute_metrics(samples((UNKNOWN, 10), (BREAK, 5)))
    assert m.on_task_ratio is None
    assert compute_metrics([]).coverage is None


def test_return_gap_and_episodes():
    m = compute_metrics(
        samples((ON, 10), (OFF, 5), (AWAY, 7), (ON, 10), (OFF, 4), (BREAK, 3), (ON, 2), (OFF, 3))
    )
    assert m.off_task_episodes == 3
    assert m.return_gaps_s == (7,)  # AWAY between off-task end and next ON_TASK
    assert m.episodes_without_return == 2  # ended by a break / by session end
    assert m.mean_off_task_s == 4
    assert m.longest_on_task_s == 10


def test_app_switches_ignore_unknown_and_self():
    m = compute_metrics(
        samples((ON, 2, "code.exe"), (ON, 1), (ON, 1, "focuslab"), (ON, 2, "Code.exe"),
                (OFF, 2, "game.exe"), (ON, 1, "code.exe"))
    )
    assert m.app_switches == 2


def test_corrections_change_effective_states_only():
    raw = samples((ON, 5), (OFF, 5), (ON, 5))
    segs = [StateSegment(5, 10, OFF, corrected_label=ON)]
    eff = apply_corrections(raw, segs)
    assert compute_metrics(eff).seconds[ON] == 15
    assert raw[5].state is OFF  # stored samples untouched


def test_format_duration():
    assert format_duration(None) == "측정 불가"
    assert format_duration(59) == "59초"
    assert format_duration(125) == "2분 5초"
    assert format_duration(3720) == "1시간 2분"
