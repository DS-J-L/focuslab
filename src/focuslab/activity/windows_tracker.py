"""Windows foreground app observation. Reads process names only, never window titles,
document names, URLs or input contents."""

import ctypes
import logging
import os
import sys
from collections.abc import Iterable

from focuslab.activity.idle_monitor import idle_seconds
from focuslab.config import LOCK_APPS, NEUTRAL_APPS, SELF_NAME
from focuslab.domain.models import ActivityObservation

log = logging.getLogger(__name__)

_DESKTOP_SWITCHDESKTOP = 0x0100


def normalize(name: str) -> str:
    return name.strip().lower()


def allowed_status(process_name: str | None, allowed_apps: Iterable[str]) -> bool | None:
    """True/False for allowed/unrelated apps; None for neutral apps or no foreground app."""
    if not process_name:
        return None
    name = normalize(process_name)
    if name in NEUTRAL_APPS:
        return None
    return name in {normalize(a) for a in allowed_apps}


def is_screen_locked() -> bool:
    """The input desktop is not accessible while the workstation is locked."""
    user32 = ctypes.windll.user32
    desktop = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def foreground_process() -> str | None:
    """Process name owning the foreground window; FocusLab itself reports ``SELF_NAME``."""
    import psutil
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if pid == os.getpid():
        return SELF_NAME
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return None


def visible_window_apps() -> list[str]:
    """Process names that currently own visible top-level windows (for the allow-list picker)."""
    if sys.platform != "win32":
        return []
    import psutil
    import win32con
    import win32gui
    import win32process

    pids: set[int] = set()

    def collect(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return True
        pids.add(win32process.GetWindowThreadProcessId(hwnd)[1])
        return True

    win32gui.EnumWindows(collect, None)
    names = set()
    for pid in pids - {os.getpid()}:
        try:
            names.add(psutil.Process(pid).name())
        except psutil.Error:
            continue
    return sorted(names, key=str.lower)


class WindowsActivitySource:
    """Samples the foreground app and idle time on each session tick (microseconds of work)."""

    def __init__(self, allowed_apps: Iterable[str]) -> None:
        self._allowed = tuple(allowed_apps)

    def sample(self, now_ms: int) -> ActivityObservation:
        if sys.platform != "win32":
            return ActivityObservation(now_ms, None, None, None, available=False)
        try:
            locked = is_screen_locked()
            name = None if locked else foreground_process()
            idle = idle_seconds()
        except Exception:  # pywin32/OS errors must not stop the session
            log.warning("activity sample failed", exc_info=True)
            return ActivityObservation(now_ms, None, None, None, available=False)
        locked = locked or bool(name and normalize(name) in LOCK_APPS)
        allowed = None if locked else allowed_status(name, self._allowed)
        return ActivityObservation(
            now_ms, None if locked else name, allowed, idle, available=True, screen_locked=locked
        )
