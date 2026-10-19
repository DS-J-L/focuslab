"""Application wiring: the session service, sensor factories and persisted user settings."""

import json
import sys

from focuslab import autostart
from focuslab.activity.probe import WindowsProbe
from focuslab.activity.recorder import (
    DEFAULT_IDLE_THRESHOLD_S,
    ActivityRecorder,
    RecorderConfig,
    RecorderState,
)
from focuslab.activity.win_events import WindowsEventThread
from focuslab.activity.windows_tracker import WindowsActivitySource
from focuslab.camera.calibration import Calibration
from focuslab.config import DEFAULT_ALLOWED_APPS, data_dir, db_path, face_model_path
from focuslab.domain.models import ActivityObservation, SessionConfig, SessionMode
from focuslab.domain.protocols import ActivitySource, FaceSource
from focuslab.mock_sources import MockActivitySource, MockFaceSource
from focuslab.services.session_service import SessionService
from focuslab.services.worker_manager import CameraFaceSource
from focuslab.ui.onboarding import OnboardingChoice


class NoActivitySource:
    """Used when the user has not agreed to PC activity observation."""

    def sample(self, now_ms: int) -> ActivityObservation:
        return ActivityObservation(now_ms, None, None, None, available=False)


class AppContext:
    def __init__(self, demo: bool = False) -> None:
        self.demo = demo
        self.data_dir = data_dir()
        self.db_path = db_path(self.data_dir)
        self.service = SessionService(
            self.db_path,
            face_factory=self._face_factory,
            activity_factory=self._activity_factory,
            calibration=self.calibration,
        )
        self.recorder: ActivityRecorder | None = None

    # settings ---------------------------------------------------------------------
    def setting(self, key: str, default: str | None = None) -> str | None:
        with self.service.lock:
            return self.service.repository.get_setting(key, default)

    def set_setting(self, key: str, value: str | None) -> None:
        with self.service.lock:
            repo = self.service.repository
            if value is None:
                repo.delete_setting(key)
            else:
                repo.set_setting(key, value)

    def flag(self, key: str, default: bool = False) -> bool:
        return self.setting(key, "1" if default else "0") == "1"

    def set_flag(self, key: str, value: bool) -> None:
        self.set_setting(key, "1" if value else "0")

    @property
    def camera_consent(self) -> bool:
        return self.flag("consent.camera")

    @property
    def activity_consent(self) -> bool | None:
        value = self.setting("consent.activity")
        return None if value is None else value == "1"

    @property
    def recording_consent(self) -> bool:
        return self.flag("consent.recording")

    @property
    def idle_threshold_s(self) -> float:
        value = self.setting("activity.idle_threshold_s")
        try:
            return float(value) if value else DEFAULT_IDLE_THRESHOLD_S
        except ValueError:
            return DEFAULT_IDLE_THRESHOLD_S

    def set_idle_threshold(self, seconds: float) -> None:
        self.set_setting("activity.idle_threshold_s", str(int(seconds)))
        if self.recorder:
            self.recorder.set_idle_threshold(seconds)

    @property
    def close_to_tray(self) -> bool:
        return self.flag("ui.close_to_tray", True)

    @property
    def camera_index(self) -> int:
        return int(self.setting("camera.index", "0") or 0)

    def calibration(self) -> Calibration:
        return Calibration.from_json(self.setting("camera.calibration"))

    @property
    def retention_days(self) -> int:
        return int(self.setting("privacy.retention_days", "0") or 0)

    def allowed_apps(self, mode: SessionMode) -> tuple[str, ...]:
        saved = self.setting(f"allowed_apps.{mode.value}")
        if saved:
            try:
                return tuple(json.loads(saved))
            except ValueError:
                pass
        return DEFAULT_ALLOWED_APPS[mode]

    def set_allowed_apps(self, mode: SessionMode, apps: tuple[str, ...] | None) -> None:
        value = None if apps is None else json.dumps(list(apps), ensure_ascii=False)
        self.set_setting(f"allowed_apps.{mode.value}", value)

    # sensors ----------------------------------------------------------------------
    def _face_factory(self, config: SessionConfig) -> FaceSource:
        if self.demo:
            return MockFaceSource()
        src = CameraFaceSource(self.camera_index, face_model_path(), self.calibration())
        src.preview_enabled = self.flag("camera.preview", True)
        src.overlay_enabled = self.flag("camera.overlay", False)
        return src

    def _activity_factory(self, config: SessionConfig) -> ActivitySource:
        if self.demo:
            return MockActivitySource(config.allowed_apps)
        if not self.activity_consent:
            return NoActivitySource()
        return WindowsActivitySource(config.allowed_apps)

    # always-on recording -------------------------------------------------------------
    def start_recording(self) -> bool:
        """Start the background recorder if the user agreed. Demo mode never reads the OS."""
        if self.demo or sys.platform != "win32" or not self.recording_consent:
            return False
        if self.recorder is None:
            self.recorder = ActivityRecorder(
                self.db_path, WindowsProbe(), events=WindowsEventThread,
                config=RecorderConfig(idle_threshold_s=self.idle_threshold_s),
            )
        # A pause chosen by the user survives restarts: nothing is read until resumed.
        self.recorder.start(paused=self.flag("activity.paused"))
        return True

    def stop_recording(self) -> None:
        if self.recorder:
            self.recorder.stop()

    @property
    def recording_state(self) -> RecorderState:
        return self.recorder.state if self.recorder else RecorderState.STOPPED

    def set_recording_paused(self, paused: bool) -> None:
        self.set_flag("activity.paused", paused)
        if self.recorder:
            (self.recorder.pause if paused else self.recorder.resume)()

    # first run ------------------------------------------------------------------------
    @property
    def needs_onboarding(self) -> bool:
        return not self.demo and not self.flag("onboarding.done")

    def apply_onboarding(self, choice: OnboardingChoice) -> None:
        self.set_flag("onboarding.done", True)
        self.set_flag("consent.recording", choice.recording)
        self.set_flag("ui.close_to_tray", choice.close_to_tray)
        self.set_idle_threshold(choice.idle_minutes * 60)
        self.set_autostart(choice.autostart)

    def set_autostart(self, on: bool) -> None:
        if sys.platform != "win32" or self.demo:
            return
        if on:
            autostart.enable()
        else:
            autostart.disable()
