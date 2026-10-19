"""Windows event sources for the recorder, on one thread with its own message loop.

``SetWinEventHook(EVENT_SYSTEM_FOREGROUND)`` reports focus changes the moment they happen, so
app switches are timed exactly instead of waiting for the next poll. Only the fact that the
foreground changed is forwarded; the recorder then reads the program itself.
"""

import ctypes
import functools
import logging
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

log = logging.getLogger(__name__)

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZEEND = 0x0017
WINEVENT_OUTOFCONTEXT = 0x0000
OBJID_WINDOW = 0
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

# WINFUNCTYPE only exists on Windows; the fallback keeps the module importable elsewhere.
WINEVENTPROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG,
    wintypes.DWORD, wintypes.DWORD,
)


@functools.cache
def _user32() -> ctypes.WinDLL:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWinEventHook.restype = wintypes.HANDLE
    user32.SetWinEventHook.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD,
    ]
    user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
    ]
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    return user32


class WindowsEventThread:
    """Calls ``on_event(name)`` from its own thread. ``stop`` unhooks and joins."""

    def __init__(self, on_event: Callable[[str], None]) -> None:
        self._on_event = on_event
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.running = False

    def start(self) -> bool:
        if sys.platform != "win32" or self._thread:
            return self.running
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="focuslab-winevents", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)
        return self.running

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        if self._thread_id:
            _user32().PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=3)
        self.running = False

    def _emit(self, name: str) -> None:
        try:
            self._on_event(name)
        except Exception:  # an exception must never unwind into the Win32 callback
            log.exception("activity event handler failed")

    def _run(self) -> None:
        user32 = _user32()
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # create the queue

        def on_win_event(hook, event, hwnd, id_object, id_child, thread, time_ms) -> None:
            if id_object == OBJID_WINDOW:
                self._emit("foreground")

        callback = WINEVENTPROC(on_win_event)  # must stay referenced while hooked
        hooks = [
            user32.SetWinEventHook(event, event, None, callback, 0, 0, WINEVENT_OUTOFCONTEXT)
            for event in (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND)
        ]
        self.running = all(hooks)
        if not self.running:
            log.warning("SetWinEventHook failed (error %s); polling only", ctypes.get_last_error())
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hook in hooks:
                if hook:
                    user32.UnhookWinEvent(hook)
            self._thread_id = 0
