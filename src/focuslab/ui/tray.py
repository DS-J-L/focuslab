"System tray icon: recording and session state, a visible camera-in-use marker and controls."

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from focuslab.activity.recorder import RecorderState
from focuslab.domain.models import CameraStatus
from focuslab.i18n import LocalizedMapping, tr
from focuslab.services.session_service import ACTIVE, Lifecycle, LiveSnapshot
from focuslab.ui.recording_status import RecordingHealth
from focuslab.ui.theme import ACCENT, STATE_COLORS, STATE_LABELS
from focuslab.ui.widgets import timer_text

PAUSED_COLOR = "#8C94A6"
SAVE_FAILED_COLOR = "#E8590C"


def make_icon(color: str | None = None, camera_on: bool = False, size: int = 64) -> QIcon:
    """Parrot mascot with optional recording and camera indicators for the tray."""
    mascot = QIcon(str(Path(__file__).with_name("icons") / "parrot-telescope.png"))
    if color is None and not camera_on:
        return mascot

    icon = QIcon()
    for edge in sorted({16, 20, 24, 32, 40, 48, size, 128, 256}):
        pixmap = QPixmap(edge, edge)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(0, 0, mascot.pixmap(edge, edge))
        p.setPen(QPen(QColor("white"), max(1.0, edge * 0.035)))
        if color is not None:
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(edge * 0.68, edge * 0.68, edge * 0.28, edge * 0.28))
        if camera_on:
            p.setBrush(QColor("#E03131"))
            p.drawEllipse(QRectF(edge * 0.68, edge * 0.04, edge * 0.28, edge * 0.28))
        p.end()
        icon.addPixmap(pixmap)
    return icon


RECORDING_TEXT = LocalizedMapping(
    {
        RecorderState.RUNNING: "Automatic recording on",
        RecorderState.PAUSED: "Automatic recording paused",
        RecorderState.STOPPED: "Automatic recording off",
    }
)


class Tray(QSystemTrayIcon):
    def __init__(self, window: QWidget) -> None:
        super().__init__(make_icon(ACCENT), window)
        self.setToolTip("FocusLab")
        menu = QMenu()
        self.health_action: QAction = menu.addAction("")  # observing and saving, as text
        self.health_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Open"), window.show_normal)
        self.recording_action: QAction = menu.addAction(
            tr("Pause recording"), window.toggle_recording_pause
        )
        self.camera_action: QAction = menu.addAction(tr("Turn off camera"), window.stop_camera)
        menu.addSeparator()
        self.pause_action: QAction = menu.addAction(tr("Pause session"), window.toggle_pause)
        self.finish_action: QAction = menu.addAction(tr("End session"), window.finish_session)
        menu.addSeparator()
        menu.addAction(tr("Quit FocusLab completely"), window.quit_app)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(
            lambda reason: (
                window.show_normal()
                if reason
                in (
                    QSystemTrayIcon.ActivationReason.Trigger,
                    QSystemTrayIcon.ActivationReason.DoubleClick,
                )
                else None
            )
        )
        self._key: tuple | None = None
        self._save_failed = False

    def update_state(
        self,
        snap: LiveSnapshot,
        recording: RecorderState,
        health: RecordingHealth | None = None,
        countdown: bool = False,
    ) -> None:
        health = health or RecordingHealth(RECORDING_TEXT[recording])
        self.health_action.setText(health.text)
        if health.saving_failed and not self._save_failed:  # once per failure, not every poll
            self.showMessage(
                "FocusLab",
                tr(
                    "Automatic recordings cannot be saved. This warning clears "
                    "after a successful save."
                ),
                QSystemTrayIcon.MessageIcon.Warning,
            )
        self._save_failed = health.saving_failed
        active = snap.lifecycle in ACTIVE
        camera_on = snap.camera_status in (CameraStatus.RUNNING, CameraStatus.STARTING)
        self.pause_action.setEnabled(active)
        self.finish_action.setEnabled(active)
        paused = snap.lifecycle is Lifecycle.PAUSED
        self.pause_action.setText(tr("Resume session") if paused else tr("Pause session"))
        self.camera_action.setVisible(camera_on)
        self.recording_action.setEnabled(recording is not RecorderState.STOPPED)
        self.recording_action.setText(
            tr("Resume recording") if recording is RecorderState.PAUSED else tr("Pause recording")
        )
        state = snap.decision.state if active and snap.decision else None
        key = (state, camera_on, snap.lifecycle, recording, health.saving_failed)
        if key != self._key:
            if state:
                color = STATE_COLORS[state]
            elif health.saving_failed:
                color = SAVE_FAILED_COLOR
            else:
                color = ACCENT if recording is RecorderState.RUNNING else PAUSED_COLOR
            self.setIcon(make_icon(color, camera_on))
            self._key = key
        parts = ["FocusLab", RECORDING_TEXT[recording]]
        if health.saving_failed:  # Windows cuts tooltips at 127 characters: keep it short
            parts.append(tr("⚠ Save failed"))
        if active:
            planned = snap.config.planned_minutes * 60 if snap.config else 0
            parts.append(tr("Session {p0}", p0=timer_text(snap.active_s, planned, countdown)))
            parts.append(
                tr("Paused")
                if snap.lifecycle is Lifecycle.PAUSED
                else (STATE_LABELS[state] if state else tr("Starting observation"))
            )
        if camera_on:
            parts.append(tr("Camera in use"))
        self.setToolTip(" · ".join(parts))
