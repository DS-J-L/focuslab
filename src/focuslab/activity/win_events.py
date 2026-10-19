"""Windows event sources for the recorder, on one thread with its own message loop.

- ``SetWinEventHook(EVENT_SYSTEM_FOREGROUND)`` reports focus changes the moment they happen,
  so app switches are timed exactly instead of waiting for the next poll.
- A hidden top-level window receives session notifications (``WTSRegisterSessionNotification``:
  lock, unlock, logon, logoff, fast user switching), power broadcasts (suspend, resume),
  display on/off (``GUID_CONSOLE_DISPLAY_STATE``) and shutdown (``WM_ENDSESSION``). Message-only
  windows do not receive broadcasts, so a never-shown top-level window is used.

Only event names are forwarded; the recorder reads the program itself.
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
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PM_NOREMOVE = 0x0000
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
NOTIFY_FOR_THIS_SESSION = 0
DEVICE_NOTIFY_WINDOW_HANDLE = 0

# WM_WTSSESSION_CHANGE wParam -> recorder event name
WTS_EVENTS = {
    0x1: "console_connect",
    0x2: "console_disconnect",
    0x5: "logon",
    0x6: "logoff",
    0x7: "lock",
    0x8: "unlock",
}

# WINFUNCTYPE only exists on Windows; the fallback keeps the module importable elsewhere.
_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
LRESULT = ctypes.c_ssize_t
WINEVENTPROC = _FUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG,
    wintypes.DWORD, wintypes.DWORD,
)
WNDPROC = _FUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556, 0x704A, 0x47A0, (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47)
)


class POWERBROADCAST_SETTING(ctypes.Structure):  # noqa: N801 (Win32 name)
    _fields_ = [("PowerSetting", GUID), ("DataLength", wintypes.DWORD), ("Data", ctypes.c_ubyte)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


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
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
    user32.RegisterPowerSettingNotification.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(GUID), wintypes.DWORD
    ]
    user32.UnregisterPowerSettingNotification.argtypes = [wintypes.HANDLE]
    return user32


@functools.cache
def _module_handle() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE  # the default int would truncate it
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    return kernel32.GetModuleHandleW(None)


@functools.cache
def _wtsapi32() -> ctypes.WinDLL:
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
    wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
    return wtsapi32


class WindowsEventThread:
    """Calls ``on_event(name)`` from its own thread. ``stop`` unhooks, unregisters and joins."""

    def __init__(self, on_event: Callable[[str], None]) -> None:
        self._on_event = on_event
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._display_on: bool | None = None
        self._asleep = False
        self.running = False  # foreground hook installed
        self.session_events = False  # lock/power/shutdown notifications registered
        self.hwnd = 0

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
        self.running = self.session_events = False

    def _emit(self, name: str) -> None:
        try:
            self._on_event(name)
        except Exception:  # an exception must never unwind into a Win32 callback
            log.exception("activity event handler failed")

    # window messages ----------------------------------------------------------------
    def handle_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        """Translate one window message; a non-None result short-circuits DefWindowProc."""
        if msg == WM_WTSSESSION_CHANGE:
            name = WTS_EVENTS.get(wparam)
            if name:
                self._emit(name)
        elif msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                self._asleep = True
                self._emit("suspend")
            elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND) and self._asleep:
                self._asleep = False  # both arrive after a user-initiated wake: report once
                self._emit("wake")
            elif wparam == PBT_POWERSETTINGCHANGE and lparam:
                setting = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                self.display_changed(setting.Data != 0)  # 0 off, 1 on, 2 dimmed
            return 1
        elif msg == WM_QUERYENDSESSION:
            return 1  # never block shutdown
        elif msg == WM_ENDSESSION and wparam:
            self._emit("session_end")
            return 0
        return None

    def display_changed(self, on: bool) -> None:
        # Windows sends the current state right after registering; report only changes
        # (and a display that is already dark).
        previous, self._display_on = self._display_on, on
        if previous is None and on:
            return
        if previous != on:
            self._emit("display_on" if on else "display_off")

    def _run(self) -> None:
        user32 = _user32()
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # create the queue

        def on_win_event(hook, event, hwnd, id_object, id_child, thread, time_ms) -> None:
            if id_object == OBJID_WINDOW:
                self._emit("foreground")

        def wnd_proc(hwnd, message, wparam, lparam):
            try:
                result = self.handle_message(message, wparam, lparam)
            except Exception:
                log.exception("activity window message failed")
                result = None
            if result is not None:
                return result
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        # Both callbacks must stay referenced while Windows may call them.
        win_event_cb, wnd_proc_cb = WINEVENTPROC(on_win_event), WNDPROC(wnd_proc)
        hooks = [
            user32.SetWinEventHook(event, event, None, win_event_cb, 0, 0, WINEVENT_OUTOFCONTEXT)
            for event in (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND)
        ]
        self.running = all(hooks)
        if not self.running:
            log.warning("SetWinEventHook failed (error %s); polling only", ctypes.get_last_error())
        class_name = f"FocusLabActivityEvents{id(self)}"  # one class per window procedure
        hinstance = _module_handle()
        hwnd, power = self._create_window(user32, wnd_proc_cb, class_name, hinstance)
        self.hwnd = hwnd
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hook in hooks:
                if hook:
                    user32.UnhookWinEvent(hook)
            if power:
                user32.UnregisterPowerSettingNotification(power)
            if hwnd:
                _wtsapi32().WTSUnRegisterSessionNotification(hwnd)
                user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, hinstance)
            self._thread_id = self.hwnd = 0

    def _create_window(self, user32, wnd_proc_cb, class_name: str, hinstance) -> tuple[int, int]:
        wc = WNDCLASSW(lpfnWndProc=wnd_proc_cb, hInstance=hinstance, lpszClassName=class_name)
        if not user32.RegisterClassW(ctypes.byref(wc)):
            log.warning("RegisterClassW failed (error %s)", ctypes.get_last_error())
            return 0, 0
        # Style 0 and never shown: a hidden top-level window that still gets broadcasts.
        hwnd = user32.CreateWindowExW(
            0, class_name, "FocusLab", 0, 0, 0, 0, 0, None, None, hinstance, None
        )
        if not hwnd:
            log.warning("activity event window failed (error %s)", ctypes.get_last_error())
            return 0, 0
        wts = _wtsapi32().WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
        power = user32.RegisterPowerSettingNotification(
            hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), DEVICE_NOTIFY_WINDOW_HANDLE
        )
        self.session_events = bool(wts)
        return hwnd, power or 0
