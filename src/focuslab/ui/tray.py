"""System tray icon showing the current estimate and a visible camera-in-use marker."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from focuslab.domain.models import CameraStatus
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.theme import ACCENT, STATE_COLORS, STATE_LABELS
from focuslab.ui.widgets import clock_text


def make_icon(color: str, camera_on: bool = False, size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(4, 4, size - 8, size - 8))
    p.setBrush(QColor("white"))
    p.drawEllipse(QRectF(size * 0.34, size * 0.34, size * 0.32, size * 0.32))
    if camera_on:
        p.setBrush(QColor("#E03131"))
        p.drawEllipse(QRectF(size * 0.62, 0, size * 0.38, size * 0.38))
    p.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, window: QWidget) -> None:
        super().__init__(make_icon(ACCENT), window)
        self.setToolTip("FocusLab")
        menu = QMenu()
        menu.addAction("열기", window.show_normal)
        self.pause_action: QAction = menu.addAction("일시정지", window.toggle_pause)
        self.finish_action: QAction = menu.addAction("세션 종료", window.finish_session)
        menu.addSeparator()
        menu.addAction("FocusLab 종료", window.quit_app)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(
            lambda reason: window.show_normal()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick)
            else None
        )
        self._key: tuple | None = None

    def update_state(self, snap: LiveSnapshot) -> None:
        active = snap.lifecycle in ACTIVE
        self.pause_action.setEnabled(active)
        self.finish_action.setEnabled(active)
        self.pause_action.setText("재개" if snap.lifecycle is Lifecycle.PAUSED else "일시정지")
        camera_on = snap.camera_status in (CameraStatus.RUNNING, CameraStatus.STARTING)
        state = snap.decision.state if active and snap.decision else None
        key = (state, camera_on, snap.lifecycle)
        if key != self._key:
            color = STATE_COLORS[state] if state else ACCENT
            self.setIcon(make_icon(color, camera_on))
            self._key = key
        if not active:
            self.setToolTip("FocusLab — 세션 없음")
            return
        parts = ["FocusLab", clock_text(snap.active_s)]
        parts.append("일시정지" if snap.lifecycle is Lifecycle.PAUSED else
                     (STATE_LABELS[state] if state else "관찰 시작 중"))
        if camera_on:
            parts.append("카메라 사용 중")
        self.setToolTip(" · ".join(parts))
