"Application wiring: the session service, sensor factories and persisted user settings."

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from focuslab import autostart
from focuslab.activity.power import EventLogPower, PowerSource
from focuslab.activity.probe import WindowsProbe
from focuslab.activity.recorder import (
    DEFAULT_IDLE_THRESHOLD_S,
    ActivityRecorder,
    RecorderConfig,
    RecorderState,
    RecorderStatus,
    wall_ms,
)
from focuslab.activity.win_events import WindowsEventThread
from focuslab.activity.windows_tracker import WindowsActivitySource
from focuslab.browser import BROWSER_EXES
from focuslab.browser.store import BrowserStateStore
from focuslab.camera.calibration import Calibration
from focuslab.config import data_dir, db_path, face_model_path
from focuslab.domain.activity import ActivitySpan, Category
from focuslab.domain.models import SessionConfig
from focuslab.domain.protocols import ActivitySource, FaceSource
from focuslab.i18n import SUPPORTED_LANGUAGES, get_language, initialize_language
from focuslab.mock_sources import DemoPower, MockActivitySource, MockFaceSource
from focuslab.relevance import model_manager
from focuslab.relevance.embedding import SemanticAnalyzer
from focuslab.relevance.feedback import RelevanceRule, RelevanceRules
from focuslab.services.session_service import NoActivitySource, SessionService
from focuslab.services.worker_manager import CameraFaceSource
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.ui.onboarding import OnboardingChoice
from focuslab.ui.recording_status import RecordingHealth, describe
from focuslab.ui.theme import THEMES
from focuslab.work_modes import BUILT_IN, WorkMode, dump_custom, load_custom

# The recorder extends its open span on every poll (1 s); older browser detail is stale.
BROWSER_DETAIL_TTL_MS = 5_000


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
        self._power: EventLogPower | None = None
        initialize_language(self.setting("ui.language"))
        self.apply_relevance_ai()

    # settings ---------------------------------------------------------------------
    @property
    def language(self) -> str:
        saved = self.setting("ui.language")
        return saved if saved in SUPPORTED_LANGUAGES else get_language()

    def set_language_preference(self, language: str) -> None:
        """Persist the next launch's language without interrupting a live session."""
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        self.set_setting("ui.language", language)

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

    def set_camera_consent(self, on: bool) -> None:
        """Withdrawing also releases the camera of a session in progress, right away."""
        self.set_flag("consent.camera", on)
        if not on:
            self.set_flag("last.camera", False)
            self.service.stop_camera()

    def set_activity_consent(self, on: bool) -> None:
        """Withdrawing also stops a session in progress from reading PC activity."""
        self.set_flag("consent.activity", on)
        if not on:
            self.service.stop_activity()

    @property
    def recording_consent(self) -> bool:
        return self.flag("consent.recording")

    @property
    def browser_consent(self) -> bool:
        return self.flag("consent.browser")

    @property
    def page_titles_consent(self) -> bool:
        return self.flag("consent.page_titles")

    def set_page_titles_consent(self, on: bool) -> None:
        """Separate browser-title opt-in; withdrawal scrubs past and pending titles."""
        if on and not self.browser_consent:
            raise ValueError("Enable browser site collection before page titles")
        self.set_flag("consent.page_titles", on)
        if self.recorder:
            self.recorder.set_title_tracking(on)
        if not on:
            self.service.forget_page_titles()
            with self.service.lock:
                BrowserStateStore(self.service.repository.conn).clear_titles()

    def set_browser_consent(self, on: bool) -> None:
        if not on:
            self.set_page_titles_consent(False)
        self.set_flag("consent.browser", on)
        if not on:  # forget the last reported site right away
            with self.service.lock:
                BrowserStateStore(self.service.repository.conn).clear_all()
        if self.recorder:
            self.recorder.set_browser_tracking(on)

    @property
    def relevance_ai(self) -> bool:
        """The user turned on the local language model for page-title relevance."""
        return self.flag("relevance.ai")

    def set_relevance_ai(self, on: bool) -> None:
        self.set_flag("relevance.ai", on)
        self.apply_relevance_ai()

    def apply_relevance_ai(self) -> None:
        """Hand the session an analyzer when the feature is on and the model is installed.

        The model itself loads lazily on its own thread the first time a title needs it.
        """
        folder = None
        if self.relevance_ai and not self.demo and model_manager.runtime_available():
            folder = model_manager.installed_dir()
        self.service.set_semantic(
            SemanticAnalyzer(lambda: model_manager.load(folder), model_manager.MODEL_VERSION)
            if folder
            else None
        )

    def relevance_rules(self) -> list[RelevanceRule]:
        with self.service.lock:
            return RelevanceRules(self.service.repository.conn).all()

    def delete_relevance_rule(self, rule_id: int) -> None:
        """Takes effect from the next session; the one in progress keeps what it loaded."""
        with self.service.lock:
            RelevanceRules(self.service.repository.conn).delete(rule_id)

    def relevance_ai_state(self) -> str | None:
        """Analyzer state (IDLE / LOADING / READY / FAILED) while one is in use."""
        analyzer = self.service.semantic
        return analyzer.state if analyzer else None

    def browser_last_report_ms(self) -> int | None:
        with self.service.lock:
            return BrowserStateStore(self.service.repository.conn).last_report_ms()

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
    def overlay_on_start(self) -> bool:
        return self.flag("ui.overlay_on_start", True)

    @property
    def theme(self) -> str:
        "Light, dark, or ``system`` (follow the Windows app mode). Light until chosen."
        saved = self.setting("ui.theme")
        return saved if saved in THEMES else "light"

    def set_theme(self, theme: str) -> None:
        if theme not in THEMES:
            raise ValueError(f"Unsupported theme: {theme}")
        self.set_setting("ui.theme", theme)

    @property
    def timer_countdown(self) -> bool:
        "Session clocks show the time left to the target instead of counting up from 0."
        return self.flag("ui.timer_countdown", False)

    @property
    def mascot_motion(self) -> str:
        "How much the overlay parrots move on their own: minimal, normal or lively."
        return self.setting("ui.mascot_motion") or "normal"

    @property
    def mascot_reactions(self) -> bool:
        "The parrots react to estimated off-task time (they never do during breaks)."
        return self.flag("ui.mascot_reactions", True)

    @property
    def flight_enabled(self) -> bool:
        "Opt-in: a parrot flies around the screen after a long off-task run."
        return self.flag("ui.mascot_flight", False)

    @property
    def flight_after_s(self) -> int:
        return int(self.setting("ui.mascot_flight_after_s") or 60)

    @property
    def flight_interval_min(self) -> int:
        return int(self.setting("ui.mascot_flight_interval_min") or 5)

    @property
    def camera_index(self) -> int:
        return int(self.setting("camera.index", "0") or 0)

    def calibration(self) -> Calibration:
        return Calibration.from_json(self.setting("camera.calibration"))

    @property
    def retention_days(self) -> int:
        return int(self.setting("privacy.retention_days", "0") or 0)

    def allowed_apps(self, mode: WorkMode) -> tuple[str, ...]:
        saved = self.setting(f"allowed_apps.{mode.key}")
        if saved:
            try:
                return tuple(json.loads(saved))
            except ValueError:
                pass
        return mode.default_apps

    def set_allowed_apps(self, mode: WorkMode, apps: tuple[str, ...] | None) -> None:
        value = None if apps is None else json.dumps(list(apps), ensure_ascii=False)
        self.set_setting(f"allowed_apps.{mode.key}", value)

    # work modes -------------------------------------------------------------------
    def custom_modes(self) -> list[WorkMode]:
        return load_custom(self.setting("modes.custom"))

    def work_modes(self) -> list[WorkMode]:
        return [*BUILT_IN, *self.custom_modes()]

    def save_work_mode(self, mode: WorkMode) -> None:
        "Add the user's mode, or replace the one with the same key."
        modes = self.custom_modes()
        keys = [m.key for m in modes]
        if mode.key in keys:
            modes[keys.index(mode.key)] = mode
        else:
            modes.append(mode)
        self.set_setting("modes.custom", dump_custom(modes))

    def delete_work_mode(self, mode: WorkMode) -> None:
        "Past sessions keep the mode's name; only the choice for new sessions goes away."
        modes = [m for m in self.custom_modes() if m.key != mode.key]
        self.set_setting("modes.custom", dump_custom(modes))
        self.set_allowed_apps(mode, None)

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
        return WindowsActivitySource(config.allowed_apps, browser_of=self._current_browser)

    def _current_browser(self, exe_name: str) -> tuple[str | None, str | None]:
        """Site and page title the recorder attached to the foreground browser right now.

        A span the recorder has not extended recently (stalled thread, paused recording) is
        stale and yields nothing. The title is dropped unless page titles are still allowed,
        so a withdrawal takes effect on the very next session tick.
        """
        status = self.recorder.status() if self.recorder else None
        current = status.current if status else None
        if not current or current.exe_name != exe_name:
            return None, None
        if wall_ms() - current.end_ms > BROWSER_DETAIL_TTL_MS:
            return None, None
        title = current.page_title if self.page_titles_consent else None
        return current.domain, title

    # always-on recording -------------------------------------------------------------
    def start_recording(self) -> bool:
        """Start the background recorder if the user agreed. Demo mode never reads the OS."""
        if self.demo or sys.platform != "win32" or not self.recording_consent:
            return False
        if self.recorder is None:
            self.recorder = ActivityRecorder(
                self.db_path,
                WindowsProbe(),
                events=WindowsEventThread,
                config=RecorderConfig(idle_threshold_s=self.idle_threshold_s),
            )
        self.recorder.set_browser_tracking(self.browser_consent)
        self.recorder.set_title_tracking(self.browser_consent and self.page_titles_consent)
        # A pause chosen by the user survives restarts: nothing is read until resumed.
        self.recorder.start(paused=self.flag("activity.paused"))
        if self._power is not None:
            self._power.enabled = True
        return True

    def stop_recording(self) -> None:
        if self.recorder:
            self.recorder.stop()
        if self._power is not None:  # withdrawing recording consent (or exiting) stops this
            self._power.enabled = False

    def power_source(self) -> PowerSource | None:
        """Power-on time for activity reports, read from the Windows event log only while
        automatic recording is consented. Demo mode never reads the OS."""
        if self.demo:
            return DemoPower()
        if sys.platform != "win32":
            return None
        if self._power is None:
            self._power = EventLogPower()
        self._power.enabled = self.recording_consent
        return self._power

    @property
    def recording_state(self) -> RecorderState:
        return self.recorder.state if self.recorder else RecorderState.STOPPED

    def recording_status(self) -> RecorderStatus | None:
        return self.recorder.status() if self.recorder else None

    def recording_health(self) -> RecordingHealth:
        """Observing and saving, separately, in words for the pages and the tray."""
        return describe(self.recording_status(), self.recording_consent)

    def set_recording_paused(self, paused: bool) -> None:
        self.set_flag("activity.paused", paused)
        if self.recorder:
            (self.recorder.pause if paused else self.recorder.resume)()

    # classification -------------------------------------------------------------------
    @contextmanager
    def activity_repo(self) -> Iterator[ActivityRepository]:
        """Activity data on the shared UI connection (the recorder has its own)."""
        with self.service.lock:
            yield ActivityRepository(self.service.repository.conn)

    @staticmethod
    def rule_target(span: ActivitySpan) -> tuple[str, str] | None:
        """What an "always" correction applies to: the site, else a non-browser program."""
        if span.domain:
            return "site", span.domain
        if span.exe_name and span.exe_name not in BROWSER_EXES:
            return "app", span.exe_name
        return None

    def correct_span(self, span: ActivitySpan, category: Category, always: bool = False) -> None:
        with self.activity_repo() as repo:
            repo.set_span_category(span.span_id, category)
            target = self.rule_target(span) if always else None
            if target:
                repo.set_rule(*target, category)
        self._rules_changed()

    def clear_span_correction(self, span: ActivitySpan) -> None:
        with self.activity_repo() as repo:
            repo.clear_span_category(span.span_id)

    def delete_rule(self, match_type: str, pattern: str) -> None:
        with self.activity_repo() as repo:
            repo.delete_rule(match_type, pattern)
        self._rules_changed()

    def set_exclusions(self, apps, sites) -> None:
        with self.activity_repo() as repo:
            repo.set_exclusions(apps, sites)
        self._rules_changed()

    def _rules_changed(self) -> None:
        if self.recorder:
            self.recorder.reload_rules()

    # first run ------------------------------------------------------------------------
    @property
    def needs_onboarding(self) -> bool:
        return not self.demo and not self.flag("onboarding.done")

    @property
    def needs_guide(self) -> bool:
        return not self.demo and not self.flag("guide.done")

    def apply_onboarding(self, choice: OnboardingChoice) -> None:
        self.set_flag("onboarding.done", True)
        self.set_language_preference(choice.language)
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
