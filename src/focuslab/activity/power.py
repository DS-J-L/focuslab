"""PC power-on time and a sleep-setting tip.

The recorder only sees time while FocusLab runs, so how long the PC was on comes from the
Windows System event log instead: boot/shutdown (Kernel-General 12/13), sleep and resume
(Kernel-Power 42/107, Power-Troubleshooter 1) and Modern Standby enter/exit (Kernel-Power
506/507). Only those timestamps and the current sleep/display timeouts are read, on demand
for a report; nothing is stored.

Power-on time is the union of the awake intervals from the log and the recorded spans, so it
never falls below what was observed (a crash leaves no shutdown event to end an interval).
"""

import ctypes
import logging
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from focuslab.domain.activity import SpanKind

log = logging.getLogger(__name__)

SUGGESTED_SLEEP_S = 30 * 60  # what the tip suggests when sleep is off or longer
MIN_TIP_MS = 15 * 60_000  # below this the tip is not worth a line
BLOCKED_MARGIN_S = 10 * 60  # a run this much past the sleep timeout means sleep was blocked
_RUN_JOIN_MS = 10_000  # idle/locked spans this close together are one stretch without input
_RESUME_LOOKAHEAD_MS = 7 * 86_400_000


@dataclass(frozen=True)
class PowerEvent:
    time_ms: int
    on: bool  # the PC was awake from this moment (boot, resume) or not (shutdown, sleep)
    boot: bool = False
    # A resume report gives the whole sleep. It wins over events logged inside it: leaving
    # Modern Standby to hibernate logs an "exit" (507) while the PC stays asleep.
    asleep_until_ms: int | None = None


@dataclass(frozen=True)
class PowerSettings:
    sleep_s: int  # 0 = never
    display_s: int  # 0 = never
    on_battery: bool = False


class PowerSource(Protocol):
    def on_intervals(self, start_ms: int, end_ms: int) -> list[tuple[int, int]] | None:
        """Awake intervals within the window, or None when the log cannot tell."""

    def settings(self) -> PowerSettings | None: ...


@dataclass(frozen=True)
class SleepTip:
    blocked: bool  # sleep is set short enough, yet the PC stayed awake past it
    runs: int  # stretches without input that ran past the threshold
    total_ms: int  # their total length
    saved_ms: int  # the part past the threshold: time that could have been asleep
    sleep_s: int


@dataclass
class PowerReport:
    on_ms: int
    unrecorded_ms: int  # awake but FocusLab recorded nothing (not running or paused)
    unused_runs: list[tuple[int, int]] = field(default_factory=list)  # idle/locked stretches
    settings: PowerSettings | None = None

    @property
    def tip(self) -> SleepTip | None:
        return sleep_tip(self.unused_runs, self.settings)


def on_intervals(events: Iterable[PowerEvent], start_ms: int, end_ms: int) -> list[tuple[int, int]]:
    """Awake intervals clipped to ``[start_ms, end_ms)``. ``events`` must include the last
    event before the window (the state before any event is off). A repeated resume is
    ignored; a boot while awake means the previous run ended without an event (a crash), so
    it is closed at the last event seen."""
    events = sorted(events, key=lambda e: e.time_ms)
    out, since, last = [], None, None
    for ev in events:
        if ev.on and since is not None and ev.boot:
            out.append((since, last))
            since = ev.time_ms
        elif ev.on and since is None:
            since = ev.time_ms
        elif not ev.on and since is not None:
            out.append((since, ev.time_ms))
            since = None
        last = ev.time_ms
    if since is not None:
        out.append((since, end_ms))
    for ev in events:
        if ev.asleep_until_ms is not None:
            out = _subtract(out, ev.time_ms, ev.asleep_until_ms)
    clipped = ((max(a, start_ms), min(b, end_ms)) for a, b in out)
    return [(a, b) for a, b in clipped if b > a]


def _subtract(intervals: list[tuple[int, int]], lo: int, hi: int) -> list[tuple[int, int]]:
    out = []
    for a, b in intervals:
        out += [(a, min(b, lo))] if a < lo else []
        out += [(max(a, hi), b)] if b > hi else []
    return [(a, b) for a, b in out if b > a]


def _union_ms(intervals: Iterable[tuple[int, int]]) -> int:
    total, cur = 0, None
    for a, b in sorted(intervals):
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    return total + (cur[1] - cur[0] if cur else 0)


def power_report(
    awake: Sequence[tuple[int, int]], spans: Sequence, settings: PowerSettings | None
) -> PowerReport:
    """``spans`` are the window's (clipped) activity spans or ``LabeledSpan`` items."""
    spans = sorted((getattr(s, "span", s) for s in spans), key=lambda s: s.start_ms)
    observed = [(s.start_ms, s.end_ms) for s in spans]
    on_ms = _union_ms([*awake, *observed])
    runs: list[tuple[int, int]] = []
    for s in spans:
        if s.kind is SpanKind.ACTIVE:
            continue
        if runs and s.start_ms - runs[-1][1] <= _RUN_JOIN_MS:
            runs[-1] = (runs[-1][0], max(runs[-1][1], s.end_ms))
        else:
            runs.append((s.start_ms, s.end_ms))
    return PowerReport(on_ms, on_ms - _union_ms(observed), runs, settings)


def sleep_tip(
    runs: Sequence[tuple[int, int]], settings: PowerSettings | None
) -> SleepTip | None:
    """One data-based suggestion, or None. Stretches without input are idle or locked time
    the recorder saw, never unrecorded time (FocusLab may simply not have been running)."""
    if settings is None:
        return None
    sleep_s = settings.sleep_s
    blocked = 0 < sleep_s <= SUGGESTED_SLEEP_S
    limit_ms = (sleep_s + BLOCKED_MARGIN_S if blocked else SUGGESTED_SLEEP_S) * 1000
    over = [b - a for a, b in runs if b - a > limit_ms]
    base_ms = (sleep_s if blocked else SUGGESTED_SLEEP_S) * 1000
    saved = sum(ms - base_ms for ms in over)
    if saved < MIN_TIP_MS:
        return None
    return SleepTip(blocked, len(over), sum(over), saved, sleep_s)


# Windows ---------------------------------------------------------------------------------

_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
_QUERY = (
    "*[System[((Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=12 or EventID=13))"
    " or (Provider[@Name='Microsoft-Windows-Kernel-Power'] and (EventID=42 or EventID=107"
    " or EventID=506 or EventID=507))"
    " or (Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1))"
    "{time}]]"
)
# (provider suffix, event id) -> awake from then on?
_STATES = {
    ("Kernel-General", 12): True,
    ("Kernel-General", 13): False,
    ("Kernel-Power", 42): False,
    ("Kernel-Power", 107): True,
    ("Kernel-Power", 506): False,
    ("Kernel-Power", 507): True,
}


def _ms(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_event(xml: str) -> list[PowerEvent]:
    """The power events in one rendered event (Power-Troubleshooter 1 carries both the
    sleep and the wake time)."""
    root = ET.fromstring(xml)
    provider = root.find("e:System/e:Provider", _NS).get("Name", "")
    event_id = int(root.findtext("e:System/e:EventID", "0", _NS))
    created = _ms(root.find("e:System/e:TimeCreated", _NS).get("SystemTime"))
    if provider.endswith("Power-Troubleshooter"):
        data = {d.get("Name"): d.text for d in root.iterfind("e:EventData/e:Data", _NS)}
        wake = _ms(data["WakeTime"]) if data.get("WakeTime") else created
        sleep = _ms(data["SleepTime"]) if data.get("SleepTime") else None
        out = [PowerEvent(sleep, False, asleep_until_ms=wake)] if sleep and sleep < wake else []
        return [*out, PowerEvent(wake, True)]
    on = _STATES.get((provider.removeprefix("Microsoft-Windows-"), event_id))
    return [] if on is None else [PowerEvent(created, on, boot=event_id == 12)]


def parse_time(xml: str) -> int:
    root = ET.fromstring(xml)
    return _ms(root.find("e:System/e:TimeCreated", _NS).get("SystemTime"))


class EventLogPower:
    """Reads the System event log with ``EvtQuery``. Past windows are cached: the log does
    not change for them."""

    def __init__(self, now_ms=None) -> None:
        self.enabled = True  # set from the GUI thread when recording consent changes
        self._now = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._cache: dict[tuple[int, int], list[tuple[int, int]] | None] = {}

    def _query(self, condition: str, *, newest_first: bool = False, count: int = 0) -> list[str]:
        import win32evtlog

        flags = win32evtlog.EvtQueryChannelPath | (
            win32evtlog.EvtQueryReverseDirection if newest_first else 0
        )
        handle = win32evtlog.EvtQuery("System", flags, condition)
        out: list[str] = []
        while not count or len(out) < count:
            batch = win32evtlog.EvtNext(handle, count - len(out) if count else 100)
            if not batch:
                break
            out += [win32evtlog.EvtRender(e, win32evtlog.EvtRenderEventXml) for e in batch]
        return out

    def on_intervals(self, start_ms: int, end_ms: int) -> list[tuple[int, int]] | None:
        if not self.enabled:
            return None
        now = self._now()
        key = (start_ms, end_ms)
        if key in self._cache:
            return self._cache[key]
        end = min(end_ms, now)
        if end <= start_ms:
            return []
        try:
            oldest = self._query("*", count=1)
            if not oldest or parse_time(oldest[0]) > start_ms:
                result = None  # the log no longer reaches back to the window
            else:
                before = self._query(
                    _QUERY.format(time=f" and TimeCreated[@SystemTime<='{_iso(start_ms)}']"),
                    newest_first=True,
                    count=1,
                )
                # A resume report is logged on waking, possibly days after the window, and
                # tells how long the PC slept inside it.
                until = min(now, end + _RESUME_LOOKAHEAD_MS)
                inside = self._query(
                    _QUERY.format(
                        time=f" and TimeCreated[@SystemTime>'{_iso(start_ms)}'"
                        f" and @SystemTime<='{_iso(until)}']"
                    )
                )
                events = [ev for xml in (*before, *inside) for ev in parse_event(xml)]
                result = on_intervals(events, start_ms, end)
        except Exception as exc:  # no pywin32, access denied, a malformed event
            log.info("power events unavailable: %s", exc)
            return None
        if end_ms <= now:
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = result
        return result

    def settings(self) -> PowerSettings | None:
        if not self.enabled:
            return None
        try:
            return read_power_settings()
        except Exception as exc:
            log.info("power settings unavailable: %s", exc)
            return None



class _GUID(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        guid = cls()
        ctypes.memmove(guid.bytes, uuid.UUID(text).bytes_le, 16)
        return guid


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_uint32), ("BatteryFullLifeTime", ctypes.c_uint32),
    ]


_SLEEP = ("238c9fa8-0aad-41ed-83f4-97be242c8f20", "29f6c1db-86da-48c5-9fdb-f2b67b1f44da")
_DISPLAY = ("7516b95f-f776-4464-8c53-06167f40cc99", "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e")


def read_power_settings() -> PowerSettings:
    """Sleep and display-off timeouts of the active power plan for the current power source
    (powrprof; read only, never changed)."""
    if sys.platform != "win32":
        raise OSError("power settings are only available on Windows")
    status = _SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise ctypes.WinError()
    on_battery = status.ACLineStatus == 0
    powrprof = ctypes.WinDLL("powrprof")
    read = powrprof.PowerReadDCValueIndex if on_battery else powrprof.PowerReadACValueIndex
    scheme = ctypes.POINTER(_GUID)()
    if powrprof.PowerGetActiveScheme(None, ctypes.byref(scheme)):
        raise OSError("PowerGetActiveScheme failed")
    try:
        values = []
        for subgroup, setting in (_SLEEP, _DISPLAY):
            value = ctypes.c_uint32()
            rc = read(
                None, scheme, ctypes.byref(_GUID.of(subgroup)), ctypes.byref(_GUID.of(setting)),
                ctypes.byref(value),
            )
            if rc:
                raise OSError(f"PowerRead*ValueIndex failed: {rc}")
            values.append(value.value)
    finally:
        ctypes.windll.kernel32.LocalFree(scheme)
    return PowerSettings(values[0], values[1], on_battery)
