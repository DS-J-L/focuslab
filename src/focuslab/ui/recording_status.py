"""Recorder health in plain words, shared by the home page, the activity page and the tray.

Observing (the recorder reads the foreground program) and saving (what it read reaches the
database) are reported separately: a recorder can observe fine while every save fails, and
that must never look like "recording"."""

from dataclasses import dataclass
from datetime import datetime

from focuslab.activity.recorder import RecorderState, RecorderStatus, wall_ms
from focuslab.i18n import tr


@dataclass(frozen=True)
class RecordingHealth:
    text: str  # one line for a page header or the tray tooltip
    saving_failed: bool = False
    detail: str = ""  # the error itself, for a tooltip or a warning banner


def _clock(ms: int, now_ms: int) -> str:
    at, now = datetime.fromtimestamp(ms / 1000), datetime.fromtimestamp(now_ms / 1000)
    return f"{at:%H:%M:%S}" if at.date() == now.date() else f"{at:%m/%d %H:%M}"


def describe(
    status: RecorderStatus | None, consent: bool, now_ms: int | None = None
) -> RecordingHealth:
    now_ms = wall_ms() if now_ms is None else now_ms
    if not consent:
        return RecordingHealth(tr("Automatic recording is off · Enable it in Settings"))
    if status is None or status.state is RecorderState.STOPPED:
        return RecordingHealth(tr("Automatic recording stopped"))
    if status.state is RecorderState.PAUSED:
        observing = tr("Automatic recording is paused")
    elif status.probe_error:
        observing = tr("● Observation unavailable (cannot read the program)")
    else:
        observing = tr("● Observing")
    last = _clock(status.last_save_ms, now_ms) if status.last_save_ms else tr("None")
    if status.save_error:
        since = _clock(status.save_failing_since_ms or now_ms, now_ms)
        return RecordingHealth(
            tr(
                "{p0} · ⚠ Save failed (since {p1}, last saved {p2})",
                p0=observing,
                p1=since,
                p2=last,
            ),
            saving_failed=True,
            detail=status.save_error,
        )
    saving = (
        tr("Saving normally · Last saved {p0}", p0=last)
        if status.last_save_ms
        else tr("Waiting to save")
    )
    return RecordingHealth(f"{observing} · {saving}", detail=status.probe_error or "")
