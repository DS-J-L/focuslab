"""Low-cost Windows probe for the always-on recorder: foreground program, idle time, lock."""

from focuslab.activity.idle_monitor import idle_seconds
from focuslab.activity.windows_tracker import foreground_app, foreground_window, is_screen_locked
from focuslab.config import LOCK_APPS
from focuslab.domain.activity import ForegroundApp, ProbeSample


class WindowsProbe:
    """One sample costs a few Win32 calls; the program identity is cached per window."""

    def __init__(self) -> None:
        self._window: tuple[int, int] | None = None
        self._app: ForegroundApp | None = None

    def sample(self) -> ProbeSample:
        idle = idle_seconds()
        if is_screen_locked():
            return ProbeSample(None, idle, locked=True)
        window = foreground_window()
        if window is None:
            return ProbeSample(None, idle)
        if window != self._window or self._app is None:
            # A window handle belongs to one process for its whole life, so (hwnd, pid)
            # identifies the program until focus moves.
            self._window, self._app = window, foreground_app(*window)
        app = self._app
        if app and app.exe_name in LOCK_APPS:
            return ProbeSample(None, idle, locked=True)
        return ProbeSample(app, idle)
