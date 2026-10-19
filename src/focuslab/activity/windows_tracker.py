"""Windows foreground app observation. Reads process names and executable version info only,
never window titles, document names, URLs or input contents."""

import ctypes
import functools
import logging
import ntpath
import os
import sys
from collections.abc import Iterable

from focuslab.activity.idle_monitor import idle_seconds
from focuslab.config import APP_NAME, LOCK_APPS, NEUTRAL_APPS, SELF_NAME
from focuslab.domain.activity import ForegroundApp
from focuslab.domain.models import ActivityObservation

log = logging.getLogger(__name__)

_DESKTOP_SWITCHDESKTOP = 0x0100
# UWP apps are drawn inside a frame window owned by this host; the real app owns a child.
_UWP_FRAME_HOST = "applicationframehost.exe"
# Executables installed by game launchers; only this yes/no hint is kept, never the path.
_GAME_FOLDERS = (
    "\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\",
    "\\battle.net\\",
)


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


@functools.lru_cache(maxsize=256)
def exe_display_name(path: str) -> str | None:
    """Product description from the executable's version resource (e.g. "Visual Studio Code")."""
    import win32api

    try:
        translations = win32api.GetFileVersionInfo(path, r"\VarFileInfo\Translation") or []
        for lang, codepage in translations:
            value = win32api.GetFileVersionInfo(
                path, rf"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
            )
            if value and value.strip():
                return value.strip()[:120]
    except Exception:  # no version resource, unreadable file, odd encodings
        return None
    return None


def process_identity(pid: int) -> ForegroundApp | None:
    """Executable name and description for ``pid``; None if the process has already exited.

    Elevated or protected processes may refuse the path; the name alone is used then, and an
    unreadable process yields ``ForegroundApp(None)`` instead of an error.
    """
    import psutil

    try:
        proc = psutil.Process(pid)
        try:
            path = proc.exe()
        except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
            path = ""
        name = ntpath.basename(path) if path else proc.name()
    except psutil.NoSuchProcess:
        return None
    except psutil.Error:
        return ForegroundApp(None)
    if not name:
        return ForegroundApp(None)
    folder = path.lower()
    return ForegroundApp(
        normalize(name),
        exe_display_name(path) if path else None,
        game_library=any(marker in folder for marker in _GAME_FOLDERS),
    )


def _uwp_app_pid(hwnd: int, host_pid: int) -> int | None:
    import win32gui
    import win32process

    pids: list[int] = []

    def collect(child: int, _: object) -> bool:
        pid = win32process.GetWindowThreadProcessId(child)[1]
        if pid != host_pid:
            pids.append(pid)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, collect, None)
    except Exception:  # the window closed while enumerating
        return None
    return pids[0] if pids else None


def foreground_window() -> tuple[int, int] | None:
    """(hwnd, pid) of the foreground window, or None while no window has focus."""
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    return hwnd, win32process.GetWindowThreadProcessId(hwnd)[1]


def foreground_app(hwnd: int, pid: int) -> ForegroundApp | None:
    if pid == os.getpid():
        return ForegroundApp(SELF_NAME, APP_NAME)
    app = process_identity(pid)
    if app and app.exe_name == _UWP_FRAME_HOST:
        inner = _uwp_app_pid(hwnd, pid)
        if inner is not None:
            app = process_identity(inner) or app
    return app


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
