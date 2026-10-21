"""The window's own title bar, so the sidebar and the page reach the top edge as one surface.

Qt draws no frame (FramelessWindowHint), but on Windows the native frame styles are put back
and the non-client messages answered here, so the window still behaves like any other: drag and
snap by the top strip, double-click to maximize, resize from the edges, the native shadow and
rounded corners, minimize/restore animations, the system menu, and the snap layouts flyout when
hovering the maximize button. Elsewhere (and off-screen in tests) Qt's system move is used.
"""

import ctypes
import sys

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QWidget

from focuslab.i18n import tr
from focuslab.ui.theme import colors

TITLE_HEIGHT = 32
BUTTON_WIDTH = 46
RESIZE_BORDER = 6  # logical px inside the window edge that resize it

# Win32 hit-test results and messages.
HTCLIENT, HTCAPTION, HTMAXBUTTON = 1, 2, 9
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_MOUSEMOVE = 0x0200
WM_NCMOUSELEAVE = 0x02A2


class CaptionButton(QAbstractButton):
    "Minimize, maximize/restore or close, drawn like the Windows 11 caption buttons."

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.maximized = False
        # Over the maximize button Windows owns the mouse (for snap layouts): its state is fed
        # in from the non-client messages rather than from Qt's hover and press.
        self.native_hover = False
        self.native_down = False
        self.setFixedSize(BUTTON_WIDTH, TITLE_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.update_label()

    def update_label(self) -> None:
        label = {
            "min": tr("Minimize"),
            "max": tr("Restore") if self.maximized else tr("Maximize"),
            "close": tr("Close"),
        }[self.kind]
        self.setToolTip(label)
        self.setAccessibleName(label)

    def set_native_state(self, hover: bool, down: bool) -> None:
        if (hover, down) != (self.native_hover, self.native_down):
            self.native_hover, self.native_down = hover, down
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        hover = self.underMouse() or self.native_hover
        down = self.isDown() or self.native_down
        palette = colors()
        glyph = QColor(palette.text if self.isActiveWindow() else palette.caption_inactive)
        if self.kind == "close" and (hover or down):
            # Windows' own close-button red, the same in light and dark mode.
            painter.fillRect(self.rect(), QColor(196, 43, 28) if hover else QColor(201, 79, 79))
            glyph = QColor(Qt.GlobalColor.white)
        elif down:
            painter.fillRect(self.rect(), QColor(palette.caption_down))
        elif hover:
            painter.fillRect(self.rect(), QColor(palette.caption_hover))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(glyph, 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        s = 5.0  # half of the 10 px glyph
        if self.kind == "min":
            painter.drawLine(QPointF(c.x() - s, c.y()), QPointF(c.x() + s, c.y()))
        elif self.kind == "close":
            painter.drawLine(c + QPointF(-s, -s), c + QPointF(s, s))
            painter.drawLine(c + QPointF(-s, s), c + QPointF(s, -s))
        elif self.maximized:  # restore: a square with a second one behind it
            painter.drawRoundedRect(QRectF(c.x() - s, c.y() - s + 2, 8, 8), 1, 1)
            painter.drawPolyline(
                [
                    c + QPointF(-s + 2, -s + 2),
                    c + QPointF(-s + 2, -s),
                    c + QPointF(s, -s),
                    c + QPointF(s, s - 2),
                    c + QPointF(s - 2, s - 2),
                ]
            )
        else:
            painter.drawRoundedRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s), 1.5, 1.5)


class TitleBar(QWidget):
    "The top strip of the page column: empty and draggable, with the caption buttons on the right."

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(TITLE_HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addStretch()
        self.min_button = CaptionButton("min")
        self.max_button = CaptionButton("max")
        self.close_button = CaptionButton("close")
        for button in (self.min_button, self.max_button, self.close_button):
            row.addWidget(button)
        self.min_button.clicked.connect(lambda: self.window().showMinimized())
        self.max_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(lambda: self.window().close())

    def toggle_maximized(self) -> None:
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def sync_state(self) -> None:
        "Window state or activation changed: swap the maximize glyph, dim when inactive."
        self.max_button.maximized = self.window().isMaximized()
        self.max_button.update_label()
        for button in (self.min_button, self.max_button, self.close_button):
            button.update()

    # Without the native frame (not Windows): drag and double-click handled by Qt.
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)


def hit_test(window: QWidget, title_bar: TitleBar, pos: QPoint) -> int:
    """What Windows should treat the point (window coordinates, logical px) as: a resize edge,
    the caption (drag), the maximize button (snap layouts), or ordinary client area."""
    x, y, w, h = pos.x(), pos.y(), window.width(), window.height()
    if not window.isMaximized():
        left, right = x < RESIZE_BORDER, x >= w - RESIZE_BORDER
        top, bottom = y < RESIZE_BORDER, y >= h - RESIZE_BORDER
        if top:
            return HTTOPLEFT if left else HTTOPRIGHT if right else HTTOP
        if bottom:
            return HTBOTTOMLEFT if left else HTBOTTOMRIGHT if right else HTBOTTOM
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
    if y >= TITLE_HEIGHT:
        return HTCLIENT
    child = window.childAt(pos)
    if child is title_bar.max_button:
        return HTMAXBUTTON
    # Anything that takes input (the other caption buttons too) keeps working as client area;
    # plain surfaces in the top strip (the title bar, the sidebar, labels) drag the window.
    while child is not None and child is not window:
        if isinstance(child, QAbstractButton) or child.focusPolicy() != Qt.FocusPolicy.NoFocus:
            return HTCLIENT
        child = child.parentWidget()
    return HTCAPTION


# Windows only: elsewhere FocusLab keeps the system's own title bar.
INTEGRATED_FRAME = sys.platform == "win32"


def native_frame_available() -> bool:
    "The real Windows platform plugin, not the off-screen one used by tests."
    return INTEGRATED_FRAME and QGuiApplication.platformName() == "windows"


class WindowsFrame:
    "Gives a frameless top-level window its native Windows frame behavior back."

    def __init__(self, window: QWidget, title_bar: TitleBar) -> None:
        from ctypes import wintypes

        self.window = window
        self.title_bar = title_bar
        self.wintypes = wintypes
        self.user32 = ctypes.windll.user32
        self.user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user32.MonitorFromWindow.restype = wintypes.HMONITOR
        self.user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.hwnd = int(window.winId())
        self._max_down = False

        gwl_style = -16
        frame_styles = 0x00040000 | 0x00C00000 | 0x00020000 | 0x00010000 | 0x00080000
        # WS_THICKFRAME | WS_CAPTION | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
        style = self.user32.GetWindowLongPtrW(self.hwnd, gwl_style)
        self.user32.SetWindowLongPtrW(self.hwnd, gwl_style, style | frame_styles)

        class MARGINS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_int) for n in ("left", "right", "top", "bottom")]

        # A 1 px sliver of DWM frame brings back the shadow (and, on Windows 11, the border
        # and rounded corners).
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
            self.hwnd, ctypes.byref(MARGINS(0, 0, 1, 0))
        )
        swp_frame_changed = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
        self.user32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, swp_frame_changed)

    def sync_state(self) -> None:
        """Windows 11 keeps rounding and outlining a maximized frameless window: square it off
        and drop the border while maximized, and give both back on restore (no-op on 10)."""
        maximized = self.window.isMaximized()
        dwm = ctypes.windll.dwmapi
        corner = ctypes.c_int(1 if maximized else 0)  # DWMWCP_DONOTROUND / DWMWCP_DEFAULT
        border = ctypes.c_uint(0xFFFFFFFE if maximized else 0xFFFFFFFF)  # COLOR_NONE / DEFAULT
        dwm.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        dwm.DwmSetWindowAttribute(self.hwnd, 34, ctypes.byref(border), ctypes.sizeof(border))

    def handle(self, message: int) -> tuple[bool, int] | None:
        "Answer one window message, or None to let Qt handle it."
        wintypes = self.wintypes
        msg = wintypes.MSG.from_address(message)
        kind = msg.message
        if kind == WM_NCCALCSIZE:
            # The whole window is client area: no native title bar or visible border.
            if msg.wParam and self.user32.IsZoomed(msg.hWnd):
                self._clip_to_work_area(msg.lParam)
            return True, 0
        if kind == WM_NCHITTEST:
            point = wintypes.POINT(
                ctypes.c_short(msg.lParam & 0xFFFF).value,
                ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value,
            )
            self.user32.ScreenToClient(msg.hWnd, ctypes.byref(point))
            ratio = self.window.devicePixelRatioF()
            local = QPoint(int(point.x / ratio), int(point.y / ratio))
            return True, hit_test(self.window, self.title_bar, local)
        button = self.title_bar.max_button
        on_max = msg.wParam == HTMAXBUTTON
        if kind == WM_NCMOUSEMOVE:
            button.set_native_state(on_max, self._max_down and on_max)
            if on_max:
                self._track_leave(msg.hWnd)
        elif kind in (WM_NCMOUSELEAVE, WM_MOUSEMOVE):
            if kind == WM_NCMOUSELEAVE:
                self._max_down = False
            button.set_native_state(False, False)
        elif kind == WM_NCLBUTTONDOWN and on_max:
            self._max_down = True
            button.set_native_state(True, True)
            return True, 0
        elif kind == WM_NCLBUTTONUP and on_max:
            if self._max_down:
                self.title_bar.toggle_maximized()
            self._max_down = False
            button.set_native_state(True, False)
            return True, 0
        elif kind == WM_NCLBUTTONDBLCLK and on_max:
            return True, 0
        return None

    def _clip_to_work_area(self, params_address: int) -> None:
        "A maximized window is placed beyond the screen by its frame width; keep the content in."
        wintypes = self.wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        rect = wintypes.RECT.from_address(params_address)  # NCCALCSIZE_PARAMS.rgrc[0]
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        monitor = self.user32.MonitorFromWindow(self.hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            work = info.rcWork
            rect.left, rect.top = max(rect.left, work.left), max(rect.top, work.top)
            rect.right, rect.bottom = min(rect.right, work.right), min(rect.bottom, work.bottom)

    def _track_leave(self, hwnd: int) -> None:
        "Ask for WM_NCMOUSELEAVE so the maximize button's hover clears when the mouse leaves."
        wintypes = self.wintypes

        class TRACKMOUSEEVENT(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND),
                ("dwHoverTime", wintypes.DWORD),
            ]

        track = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x0002 | 0x0010, hwnd, 0)
        self.user32.TrackMouseEvent(ctypes.byref(track))  # TME_LEAVE | TME_NONCLIENT
