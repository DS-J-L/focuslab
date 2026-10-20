"Settings: consent, data location/retention/export/delete, camera device, model, calibration."

import sys
import threading
import urllib.error
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab import __version__, autostart, updater
from focuslab.activity.recorder import RecorderState
from focuslab.browser import extension
from focuslab.browser import install as browser_install
from focuslab.config import (
    MODE_PROFILES,
    RULE_VERSION,
    RuleConfig,
    face_model_path,
)
from focuslab.domain.activity import Category
from focuslab.i18n import SUPPORTED_LANGUAGES, get_language, tr
from focuslab.model_fetch import FACE_MODEL_URL, fetch_face_model
from focuslab.relevance import model_manager
from focuslab.services.export_service import (
    apply_retention,
    delete_all,
    export_activity_csv,
    export_csv,
    export_json,
)
from focuslab.ui.calibration_dialog import CalibrationDialog
from focuslab.ui.consent import (
    ask_activity_consent,
    ask_browser_consent,
    ask_camera_consent,
    ask_page_titles_consent,
    ask_recording_consent,
)
from focuslab.ui.context import AppContext
from focuslab.ui.theme import CATEGORY_LABELS, style_form
from focuslab.ui.update_dialog import UpdateDialog

COLLECTED = (
    "<b>Saved</b>: session goals, modes and times; per-second estimated states and "
    "evidence codes; foreground process names; program intervals and product names "
    "when automatic recording is enabled; your corrections, self-reports and "
    "settings.<br><b>Never saved</b>: camera video or photos, face coordinates, "
    "audio, typed content, window titles, executable paths, URLs, or "
    "screenshots. Browser page titles are stored ONLY when separately enabled.<br>"
    "All records stay on this PC and are never sent to a server."
)


class _Signals(QObject):
    modelFetched = Signal(str)
    relevanceProgress = Signal(int)  # percent of the relevance model downloaded
    relevanceFetched = Signal(str)  # "" on success, else the error
    updateChecked = Signal(object)  # Release, None (nothing published yet) or an exception


def camera_names() -> list[str]:
    try:
        from PySide6.QtMultimedia import QMediaDevices

        return [d.description() for d in QMediaDevices.videoInputs()]
    except Exception:  # QtMultimedia backend missing: fall back to indices
        return []


MOTION_LABELS = {  # message IDs, translated when the combo box is built
    "minimal": "Minimal: breathing and blinking",
    "normal": "Normal: dozing, singing, playing",
    "lively": "Lively: more often, more together",
}


class SettingsPage(QWidget):
    dataChanged = Signal()
    updateAvailable = Signal(str)  # newer version number
    restartForUpdate = Signal(object)  # unpacked folder to swap in after quitting
    overlayChanged = Signal()  # the parrots' settings changed

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._release: updater.Release | None = None
        self._staged: Path | None = None  # unpacked update waiting for a restart
        self._update_dialog: UpdateDialog | None = None
        self._quiet_check = False
        self._signals = _Signals()
        self._signals.modelFetched.connect(self._model_fetched)
        self._signals.relevanceProgress.connect(self._relevance_progress)
        self._signals.relevanceFetched.connect(self._relevance_fetched)
        self._relevance_cancel: threading.Event | None = None
        self._signals.updateChecked.connect(self._update_checked)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget(objectName="PageContent")
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)
        root.addWidget(QLabel(tr("Settings"), objectName="PageTitle"))
        root.addWidget(self._language_box())
        root.addWidget(self._privacy_box())
        root.addWidget(self._browser_box())
        root.addWidget(self._relevance_box())
        root.addWidget(self._classify_box())
        root.addWidget(self._camera_box())
        root.addWidget(self._rules_box())
        root.addWidget(self._updates_box())
        root.addStretch()
        self.refresh()

    # sections ---------------------------------------------------------------------
    def _language_box(self) -> QGroupBox:
        box = QGroupBox(tr("Appearance"))
        form = QFormLayout(box)
        style_form(form)
        self.language_combo = QComboBox()
        for code, name in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.ctx.language))
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        form.addRow(tr("Language"), self.language_combo)
        self.language_notice = QLabel(wordWrap=True, objectName="Muted")
        form.addRow(self.language_notice)
        self._refresh_language_notice()
        self.overlay_on_start = QCheckBox(tr("Show the overlay when a session starts"))
        self.overlay_on_start.toggled.connect(
            lambda on: self.ctx.set_flag("ui.overlay_on_start", on)
        )
        form.addRow(tr("Session overlay"), self.overlay_on_start)
        self.mascot_motion = QComboBox()
        for level, label in MOTION_LABELS.items():
            self.mascot_motion.addItem(tr(label), level)
        self.mascot_motion.setCurrentIndex(
            max(0, self.mascot_motion.findData(self.ctx.mascot_motion))
        )
        self.mascot_motion.currentIndexChanged.connect(self._motion_changed)
        form.addRow(tr("Parrot movement"), self.mascot_motion)
        self.mascot_reactions = QCheckBox(tr("Parrots react when you seem to be off task"))
        self.mascot_reactions.setToolTip(
            tr(
                "Off task is an estimate. The parrots first just look at you and only get "
                "cross after 30 seconds without a break in it."
            )
        )
        self.mascot_reactions.toggled.connect(self._reactions_changed)
        form.addRow("", self.mascot_reactions)
        self.mascot_flight = QCheckBox(tr("A parrot flies around the screen if it goes on"))
        self.mascot_flight.setToolTip(
            tr(
                "It hovers in front of your work saying \"Focus!\" and flies back when you "
                "return, pause or take a break, or when you click it. Keyboard input is never "
                "blocked, and it does not fly over full-screen programs."
            )
        )
        self.mascot_flight.toggled.connect(self._flight_changed)
        self.flight_after = QSpinBox()
        self.flight_after.setRange(30, 600)
        self.flight_after.setSingleStep(10)
        self.flight_after.setSuffix(tr(" s off task"))
        self.flight_after.valueChanged.connect(
            lambda v: self._overlay_setting("ui.mascot_flight_after_s", v)
        )
        self.flight_interval = QSpinBox()
        self.flight_interval.setRange(1, 60)
        self.flight_interval.setPrefix(tr("at most every "))
        self.flight_interval.setSuffix(tr(" min"))
        self.flight_interval.valueChanged.connect(
            lambda v: self._overlay_setting("ui.mascot_flight_interval_min", v)
        )
        form.addRow("", self.mascot_flight)
        form.addRow(tr("Fly after"), _row(self.flight_after, self.flight_interval))
        return box

    def _flight_changed(self, on: bool) -> None:
        self.ctx.set_flag("ui.mascot_flight", on)
        self._refresh_flight()
        self.overlayChanged.emit()

    def _overlay_setting(self, key: str, value: int) -> None:
        self.ctx.set_setting(key, str(value))
        self.overlayChanged.emit()

    def _refresh_flight(self) -> None:
        on = self.ctx.flight_enabled
        self.flight_after.setEnabled(on)
        self.flight_interval.setEnabled(on)

    def _reactions_changed(self, on: bool) -> None:
        self.ctx.set_flag("ui.mascot_reactions", on)
        self.overlayChanged.emit()

    def _motion_changed(self) -> None:
        self.ctx.set_setting("ui.mascot_motion", self.mascot_motion.currentData())
        self.overlayChanged.emit()

    def _language_changed(self) -> None:
        self.ctx.set_language_preference(self.language_combo.currentData())
        self._refresh_language_notice()

    def _refresh_language_notice(self) -> None:
        self.language_notice.setText(
            tr("Restart FocusLab to apply the selected language. Your session continues.")
            if self.ctx.language != get_language()
            else tr("Changes apply after restarting.")
        )

    def _privacy_box(self) -> QGroupBox:
        box = QGroupBox(tr("Privacy and data"))
        form = QFormLayout(box)
        style_form(form)
        info = QLabel(tr(COLLECTED), wordWrap=True)
        info.setStyleSheet("font-weight:400;")
        form.addRow(info)

        self.recording_state = QLabel(wordWrap=True)
        self.recording_button = QPushButton()
        self.recording_button.clicked.connect(self._toggle_recording)
        self.recording_pause = QPushButton()
        self.recording_pause.clicked.connect(self._toggle_recording_pause)
        form.addRow(
            tr("Automatic activity recording"),
            _row(self.recording_state, self.recording_button, self.recording_pause),
        )
        self.idle_minutes = QSpinBox()
        self.idle_minutes.setRange(1, 60)
        self.idle_minutes.setSuffix(tr(" min"))
        self.idle_minutes.valueChanged.connect(self._idle_changed)
        idle_hint = QLabel(
            tr("After this period without input, record idle time starting from the last input"),
            objectName="Muted",
            wordWrap=True,
        )
        form.addRow(tr("Idle threshold"), _row(self.idle_minutes, idle_hint))
        self.autostart = QCheckBox(tr("Start in the tray at Windows sign-in"))
        self.autostart.toggled.connect(self._autostart_toggled)
        self.close_to_tray = QCheckBox(tr("Keep recording in the tray when the window is closed"))
        self.close_to_tray.toggled.connect(lambda on: self.ctx.set_flag("ui.close_to_tray", on))
        form.addRow(tr("Background"), _row(self.autostart, self.close_to_tray))

        self.activity_state = QLabel()
        self.activity_button = QPushButton()
        self.activity_button.clicked.connect(self._toggle_activity)
        form.addRow(tr("PC activity observation"), _row(self.activity_state, self.activity_button))
        self.camera_state = QLabel()
        self.camera_button = QPushButton()
        self.camera_button.clicked.connect(self._toggle_camera)
        form.addRow(tr("Camera observation"), _row(self.camera_state, self.camera_button))

        path = QLabel(str(self.ctx.data_dir), wordWrap=True)
        open_dir = QPushButton(tr("Open folder"))
        open_dir.clicked.connect(self._open_data_dir)
        form.addRow(tr("Storage location"), _row(path, open_dir))

        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSuffix(tr(" days"))
        self.retention.setSpecialValueText(tr("Unlimited"))
        apply = QPushButton(tr("Apply"))
        apply.clicked.connect(self._apply_retention)
        form.addRow(tr("Retention period"), _row(self.retention, apply))

        exp_json = QPushButton(tr("Export all JSON"))
        exp_json.clicked.connect(lambda: self._export_all("json"))
        exp_csv = QPushButton(tr("Export all CSV"))
        exp_csv.clicked.connect(lambda: self._export_all("csv"))
        self.delete_all_button = QPushButton(tr("Delete all records"), objectName="Danger")
        self.delete_all_button.clicked.connect(self._delete_all)
        exp_activity = QPushButton(tr("Activity records CSV"))
        exp_activity.clicked.connect(lambda: self._export_all("activity"))
        form.addRow(
            tr("Export / delete"), _row(exp_json, exp_csv, exp_activity, self.delete_all_button)
        )
        return box

    def _browser_box(self) -> QGroupBox:
        box = QGroupBox(tr("Browser site recording (Chrome / Edge, optional)"))
        form = QFormLayout(box)
        style_form(form)
        self.browser_state = QLabel(wordWrap=True)
        self.browser_button = QPushButton()
        self.browser_button.clicked.connect(self._toggle_browser)
        form.addRow(tr("Consent"), _row(self.browser_state, self.browser_button))
        self.page_titles_check = QCheckBox(tr("Save active page titles (optional)"))
        self.page_titles_check.toggled.connect(self._toggle_page_titles)
        form.addRow(tr("Page details"), self.page_titles_check)
        form.addRow(
            QLabel(
                tr("Off by default. Saved only on this PC; turning off deletes saved titles."),
                wordWrap=True,
                objectName="Muted",
            )
        )
        self.host_state = QLabel(wordWrap=True)
        self.host_install = QPushButton(tr("Install connection"))
        self.host_install.clicked.connect(self._install_host)
        self.host_remove = QPushButton(tr("Remove connection"))
        self.host_remove.clicked.connect(self._remove_host)
        form.addRow(
            tr("Desktop connection"), _row(self.host_state, self.host_install, self.host_remove)
        )
        self.ext_buttons = {
            "chrome": QPushButton(tr("Install in Chrome")),
            "edge": QPushButton(tr("Install in Edge")),
        }
        for browser, button in self.ext_buttons.items():
            button.clicked.connect(lambda _=False, b=browser: self._install_extension(b))
        guide = QLabel(
            tr(
                "One click asks for consent if needed, installs the desktop connection, and "
                "opens the browser with the extension folder and short steps. Program "
                "recording works even without the extension."
            ),
            wordWrap=True,
            objectName="Muted",
        )
        form.addRow(tr("Extension"), _row(*self.ext_buttons.values()))
        form.addRow(guide)
        return box

    def _install_extension(self, browser: str) -> None:
        if not self.ctx.browser_consent:
            if not ask_browser_consent(self):
                return
            self.ctx.set_browser_consent(True)
        if not self._install_host():  # rewrite it so newly listed store origins are allowed
            return
        try:
            url = extension.store_url(browser)
            if url:
                extension.open_in_browser(browser, url)
            else:
                folder = extension.stage_extension(self.ctx.data_dir)
                page = extension.EXTENSIONS_PAGES[browser]
                QGuiApplication.clipboard().setText(page)
                extension.reveal(folder)
                extension.open_in_browser(browser)
                QMessageBox.information(
                    self,
                    tr("Install the extension"),
                    tr(
                        "A browser window and the extension folder are now open.\n\n"
                        "1. In the browser's address bar press Ctrl+V, then Enter "
                        "({p0} is already copied).\n"
                        "2. Turn on Developer mode on that page.\n"
                        "3. Drag the selected 'browser-extension' folder from Explorer onto "
                        "the page.\n"
                        "4. When 'FocusLab Activity Bridge' appears, you are done. "
                        "'Last received' here updates once you browse.",
                        p0=page,
                    ),
                )
        except OSError as exc:
            QMessageBox.warning(
                self, tr("Install the extension"), tr("Could not install: {p0}", p0=exc)
            )
        self.refresh()

    def _refresh_browser(self) -> None:
        consent = self.ctx.browser_consent
        last = self.ctx.browser_last_report_ms()
        seen = (
            tr(" · Last received {p0:%m/%d %H:%M:%S}", p0=datetime.fromtimestamp(last / 1000))
            if last
            else tr(" · No reports received yet")
        )
        self.browser_state.setText((tr("Agreed") + seen) if consent else tr("Not agreed"))
        self.browser_button.setText(tr("Withdraw") if consent else tr("Consent"))
        registered = browser_install.registered()
        names = [name.title() for name, ok in registered.items() if ok]
        self.host_state.setText(
            (tr("Connected: ") + ", ".join(names)) if names else tr("Not installed")
        )
        windows = sys.platform == "win32" and not self.ctx.demo
        self.host_install.setEnabled(windows)
        self.host_remove.setEnabled(windows and bool(names))
        for browser, button in self.ext_buttons.items():
            button.setEnabled(windows and extension.browser_executable(browser) is not None)
        self.browser_button.setEnabled(not self.ctx.demo)
        self.page_titles_check.blockSignals(True)
        self.page_titles_check.setChecked(self.ctx.page_titles_consent)
        self.page_titles_check.setEnabled(windows and consent)
        self.page_titles_check.blockSignals(False)

    def _toggle_browser(self) -> None:
        if self.ctx.browser_consent:
            self.ctx.set_browser_consent(False)
        elif ask_browser_consent(self):
            self.ctx.set_browser_consent(True)
            if not any(browser_install.registered().values()):
                self._install_host()
        self.refresh()

    def _toggle_page_titles(self, enabled: bool) -> None:
        if enabled and not ask_page_titles_consent(self):
            self.refresh()
            return
        self.ctx.set_page_titles_consent(enabled)
        self.refresh()

    def _install_host(self) -> bool:
        try:
            browser_install.install(self.ctx.data_dir)
        except OSError as exc:
            QMessageBox.warning(
                self, tr("Browser connection"), tr("Could not install: {p0}", p0=exc)
            )
            return False
        finally:
            self.refresh()
        return True

    def _remove_host(self) -> None:
        browser_install.uninstall(self.ctx.data_dir)
        self.refresh()

    def _relevance_box(self) -> QGroupBox:
        box = QGroupBox(tr("Task relevance AI (optional, on this PC)"))
        form = QFormLayout(box)
        style_form(form)
        form.addRow(
            QLabel(
                tr(
                    "Compares the session goal with the active page title using a small "
                    "language model that runs only on this PC. It needs page titles (above). "
                    "Without the model, FocusLab uses simple rules. Nothing is sent anywhere."
                ),
                wordWrap=True,
                objectName="Muted",
            )
        )
        self.relevance_check = QCheckBox(tr("Use the local language model"))
        self.relevance_check.toggled.connect(self._toggle_relevance)
        form.addRow(tr("Model analysis"), self.relevance_check)
        self.relevance_state = QLabel(wordWrap=True)
        self.relevance_remove = QPushButton(tr("Remove model"))
        self.relevance_remove.clicked.connect(self._remove_relevance_model)
        form.addRow(tr("Model"), _row(self.relevance_state, self.relevance_remove))
        return box

    def _refresh_relevance(self) -> None:
        downloading = self._relevance_cancel is not None
        status = model_manager.status()
        texts = {
            model_manager.ModelStatus.READY: tr("Installed ({p0}, {p1} license)"),
            model_manager.ModelStatus.NOT_INSTALLED: tr("Not installed"),
            model_manager.ModelStatus.RUNTIME_MISSING: tr("Unavailable in this build"),
        }
        text = texts[status].format(p0=model_manager.MODEL_VERSION, p1=model_manager.LICENSE)
        if self.ctx.relevance_ai_state() == "FAILED":
            text = tr("Could not load the model; using rules only")
        if not downloading:
            self.relevance_state.setText(text)
        self.relevance_check.blockSignals(True)
        self.relevance_check.setChecked(self.ctx.relevance_ai and status is status.READY)
        self.relevance_check.setEnabled(
            not self.ctx.demo and not downloading and status is not status.RUNTIME_MISSING
        )
        self.relevance_check.blockSignals(False)
        self.relevance_remove.setEnabled(not downloading and status is status.READY)

    def _toggle_relevance(self, enabled: bool) -> None:
        if not enabled:
            self.ctx.set_relevance_ai(False)
        elif model_manager.status() is model_manager.ModelStatus.READY:
            self.ctx.set_relevance_ai(True)
        else:
            self._download_relevance_model()
        self.refresh()

    def _download_relevance_model(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("Download relevance model"),
            tr(
                "Download {p0} (about {p1} MB, {p2} license) from Hugging Face and verify "
                "its SHA256. It runs only on this PC.\n\n{p3}",
                p0=model_manager.UPSTREAM,
                p1=round(model_manager.DOWNLOAD_BYTES / 1e6),
                p2=model_manager.LICENSE,
                p3=model_manager.MODEL_FILE.url,
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        cancel = self._relevance_cancel = threading.Event()
        self.relevance_state.setText(tr("Downloading…"))

        def work() -> None:
            try:
                model_manager.install(
                    progress=lambda done, total: self._signals.relevanceProgress.emit(
                        done * 100 // total
                    ),
                    cancel=cancel,
                )
                self._signals.relevanceFetched.emit("")
            except Exception as exc:  # network, disk or checksum errors are shown
                self._signals.relevanceFetched.emit(str(exc) or type(exc).__name__)

        threading.Thread(target=work, daemon=True).start()

    def _relevance_progress(self, percent: int) -> None:
        self.relevance_state.setText(tr("Downloading… {p0}%", p0=percent))

    def _relevance_fetched(self, error: str) -> None:
        self._relevance_cancel = None
        if error:
            QMessageBox.warning(
                self, tr("Relevance model"), tr("Could not download: {p0}", p0=error)
            )
        else:
            self.ctx.set_relevance_ai(True)
        self.refresh()

    def _remove_relevance_model(self) -> None:
        self.ctx.set_relevance_ai(False)
        model_manager.remove()
        self.refresh()

    def _classify_box(self) -> QGroupBox:
        box = QGroupBox(tr("Activity classification rules and exclusions"))
        layout = QVBoxLayout(box)
        layout.addWidget(
            QLabel(
                tr(
                    "When correcting an interval on Activity, choose 'Always "
                    "apply to this app / site' to create a rule. Corrections "
                    "are optional; built-in rules classify activity "
                    "automatically."
                ),
                wordWrap=True,
                objectName="Muted",
            )
        )
        self.rules = QListWidget()
        self.rules.setMaximumHeight(110)
        delete_rule = QPushButton(tr("Delete selected rule"))
        delete_rule.clicked.connect(self._delete_rule)
        layout.addWidget(QLabel(tr("My classification rules")))
        layout.addWidget(self.rules)
        layout.addWidget(_row(delete_rule))

        self.excluded_apps = QListWidget()
        self.excluded_sites = QListWidget()
        lists = QHBoxLayout()
        for title, widget, kind in (
            (tr("Programs to exclude (for example, keepass.exe)"), self.excluded_apps, "app"),
            (tr("Sites to exclude (for example, bank.com)"), self.excluded_sites, "site"),
        ):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            widget.setMaximumHeight(100)
            col.addWidget(widget)
            add = QPushButton(tr("Add…"))
            add.clicked.connect(lambda _=False, k=kind: self._add_exclusion(k))
            remove = QPushButton(tr("Remove selected"))
            remove.clicked.connect(lambda _=False, w=widget: self._remove_exclusion(w))
            col.addWidget(_row(add, remove))
            lists.addLayout(col)
        layout.addLayout(lists)
        layout.addWidget(
            QLabel(
                tr(
                    "Excluded items retain only unnamed 'Excluded' time. "
                    "Previously saved records are unchanged."
                ),
                wordWrap=True,
                objectName="Muted",
            )
        )
        return box

    def _refresh_classification(self) -> None:
        with self.ctx.activity_repo() as repo:
            rules = repo.rules()
            apps, sites = repo.exclusions()
        self.rules.clear()
        for row in rules:
            kind = tr("Site") if row["match_type"] == "site" else tr("Program")
            item = QListWidgetItem(
                f"{kind} {row['pattern']} → {CATEGORY_LABELS[Category(row['category'])]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, (row["match_type"], row["pattern"]))
            self.rules.addItem(item)
        for widget, values in ((self.excluded_apps, apps), (self.excluded_sites, sites)):
            widget.clear()
            widget.addItems(sorted(values))

    def _delete_rule(self) -> None:
        for item in self.rules.selectedItems():
            self.ctx.delete_rule(*item.data(Qt.ItemDataRole.UserRole))
        self.refresh()

    def _current_exclusions(self) -> tuple[list[str], list[str]]:
        def values(w: QListWidget) -> list[str]:
            return [w.item(i).text() for i in range(w.count())]

        return values(self.excluded_apps), values(self.excluded_sites)

    def _add_exclusion(self, kind: str) -> None:
        label = (
            tr("Executable name (for example, keepass.exe)")
            if kind == "app"
            else tr("Site (for example, bank.com)")
        )
        text, ok = QInputDialog.getText(self, tr("Add recording exclusion"), label)
        value = text.strip().lower()
        if not ok or not value:
            return
        if kind == "site":
            value = value.split("://")[-1].split("/")[0].removeprefix("www.")
        apps, sites = self._current_exclusions()
        (apps if kind == "app" else sites).append(value)
        self.ctx.set_exclusions(apps, sites)
        self.refresh()

    def _remove_exclusion(self, widget: QListWidget) -> None:
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))
        self.ctx.set_exclusions(*self._current_exclusions())
        self.refresh()

    def _camera_box(self) -> QGroupBox:
        box = QGroupBox(tr("Camera"))
        form = QFormLayout(box)
        style_form(form)
        self.device = QComboBox()
        self.device.currentIndexChanged.connect(self._device_changed)
        form.addRow(tr("Device"), self.device)
        self.model_state = QLabel(wordWrap=True)
        self.model_button = QPushButton(tr("Download face model"))
        self.model_button.clicked.connect(self._fetch_model)
        form.addRow(tr("Face model"), _row(self.model_state, self.model_button))
        self.calib_state = QLabel(wordWrap=True)
        self.calib_button = QPushButton(tr("Start calibration"))
        self.calib_button.clicked.connect(self._calibrate)
        reset = QPushButton(tr("Reset"))
        reset.clicked.connect(self._reset_calibration)
        form.addRow(tr("Head pose calibration"), _row(self.calib_state, self.calib_button, reset))
        return box

    def _rules_box(self) -> QGroupBox:
        cfg = RuleConfig()
        box = QGroupBox(tr("Estimation rules ({p0}, untuned hypotheses)", p0=RULE_VERSION))
        layout = QVBoxLayout(box)
        modes = ", ".join(
            tr(
                "{p0}: away {p1:.0f}s / looking away {p2:.0f}s",
                p0=m.value,
                p1=p.away_face_absent_s,
                p2=p.head_away_s,
            )
            for m, p in MODE_PROFILES.items()
        )
        text = tr(
            (
                "• Non-allowed app for at least {p0:.0f}s → possibly off task<br>• Face absent + "
                "no input for at least {p1:.0f}s → estimated away<br>• Looking away + no input "
                "for at least {p2:.0f}s → possibly off task (looking down alone does not "
                "qualify)<br>• Face observations older than {p3:.0f}s and PC observations older "
                "than {p4:.0f}s become unavailable<br>• Switching to task-related or unknown "
                "requires {p5:.0f}s of sustained evidence (prevents flicker)<br>• By mode: {p6}"
            ),
            p0=cfg.unrelated_app_s,
            p1=cfg.away_idle_s,
            p2=cfg.head_away_idle_s,
            p3=cfg.face_ttl_ms / 1000,
            p4=cfg.activity_ttl_ms / 1000,
            p5=cfg.enter_dwell_s,
            p6=modes,
        )
        label = QLabel(text, wordWrap=True)
        label.setStyleSheet("font-weight:400;")
        layout.addWidget(label)
        return box

    def _updates_box(self) -> QGroupBox:
        box = QGroupBox(tr("Updates"))
        form = QFormLayout(box)
        style_form(form)
        form.addRow(tr("Version"), QLabel(tr("FocusLab {p0}", p0=__version__)))
        self.update_auto = QCheckBox(tr("Check for updates when FocusLab starts"))
        self.update_auto.toggled.connect(lambda on: self.ctx.set_flag("update.auto_check", on))
        self.update_check = QPushButton(tr("Check now"))
        self.update_check.clicked.connect(lambda: self.check_updates())
        self.update_button = QPushButton(tr("Update"), objectName="Primary")
        self.update_button.clicked.connect(self.start_update)
        self.update_button.setVisible(False)
        form.addRow(tr("Check"), _row(self.update_auto, self.update_check, self.update_button))
        self.update_state = QLabel(wordWrap=True)
        form.addRow("", self.update_state)
        form.addRow(
            QLabel(
                tr(
                    "A check asks GitHub (api.github.com) for the latest FocusLab release. "
                    "Like any web request it reveals your IP address and FocusLab version; "
                    "no records are sent. Updates are verified with SHA256 before installing."
                ),
                wordWrap=True,
                objectName="Muted",
            )
        )
        return box

    # refresh ----------------------------------------------------------------------
    def refresh(self) -> None:
        self._refresh_recording()
        self._refresh_browser()
        self._refresh_relevance()
        self._refresh_classification()
        activity = self.ctx.activity_consent
        consent_text = {None: tr("Not asked yet"), True: tr("Agreed"), False: tr("Not agreed")}
        self.activity_state.setText(consent_text[activity])
        self.activity_button.setText(tr("Withdraw") if activity else tr("Consent"))
        camera = self.ctx.camera_consent
        self.camera_state.setText(tr("Agreed") if camera else tr("Not agreed"))
        self.camera_button.setText(tr("Withdraw") if camera else tr("Consent"))
        self.retention.setValue(self.ctx.retention_days)

        self.device.blockSignals(True)
        self.device.clear()
        names = camera_names() or [tr("Camera 0")]
        for i, name in enumerate(names):
            self.device.addItem(f"{i}: {name}")
        self.device.setCurrentIndex(min(self.ctx.camera_index, len(names) - 1))
        self.device.blockSignals(False)

        model = face_model_path()
        self.model_state.setText(
            tr("Installed: {p0}", p0=model)
            if model
            else tr("Missing — using PC activity without a camera")
        )
        self.model_button.setVisible(model is None)
        calib = self.ctx.calibration()
        if calib.calibrated:
            self.calib_state.setText(
                tr(
                    "Calibrated · Horizontal ±{p0:.0f}°, down {p1:.0f}°",
                    p0=calib.yaw_limit,
                    p1=calib.down_limit,
                )
            )
        else:
            self.calib_state.setText(tr("Using defaults (horizontal ±25°, down 20°)"))
        if not self.ctx.camera_consent:
            self.calib_state.setText(
                self.calib_state.text() + tr(" · Camera consent required for calibration")
            )
        self.calib_button.setEnabled(model is not None and self.ctx.camera_consent)

    def _refresh_recording(self) -> None:
        recorder = self.ctx.recorder
        status = recorder.status() if recorder else None
        if not self.ctx.recording_consent:
            text = tr("Off (consent not given)")
        elif status is None or status.state is RecorderState.STOPPED:
            text = (
                tr("Agreed · Recording stopped")
                if not self.ctx.demo
                else tr("Recording disabled in demo mode")
            )
        elif status.state is RecorderState.PAUSED:
            text = tr("Recording paused")
        else:
            current = status.current
            name = (current.display_name or current.exe_name) if current else None
            text = tr("Recording") + (tr(" · Current: {p0}", p0=name) if name else "")
        if status is not None and status.save_error:
            text += tr(" · ⚠ Save failed (see Activity for details)")
        self.recording_state.setText(text)
        self.recording_button.setText(
            tr("Turn off") if self.ctx.recording_consent else tr("Turn on")
        )
        self.recording_button.setEnabled(not self.ctx.demo)
        running = status is not None and status.state is not RecorderState.STOPPED
        self.recording_pause.setVisible(running)
        self.recording_pause.setText(
            tr("Resume") if status and status.state is RecorderState.PAUSED else tr("Paused")
        )
        for widget, value in (
            (self.idle_minutes, round(self.ctx.idle_threshold_s / 60)),
            (self.autostart, autostart.is_enabled()),
            (self.close_to_tray, self.ctx.close_to_tray),
            (self.overlay_on_start, self.ctx.overlay_on_start),
            (self.mascot_reactions, self.ctx.mascot_reactions),
            (self.mascot_flight, self.ctx.flight_enabled),
            (self.flight_after, self.ctx.flight_after_s),
            (self.flight_interval, self.ctx.flight_interval_min),
            (self.update_auto, self.ctx.flag("update.auto_check")),
        ):
            widget.blockSignals(True)
            (widget.setValue if isinstance(widget, QSpinBox) else widget.setChecked)(value)
            widget.blockSignals(False)
        self.autostart.setEnabled(not self.ctx.demo)
        self._refresh_flight()

    def set_session_active(self, active: bool) -> None:
        self.calib_button.setEnabled(
            not active and face_model_path() is not None and self.ctx.camera_consent
        )
        self.delete_all_button.setEnabled(not active)

    # actions ----------------------------------------------------------------------
    def _toggle_recording_pause(self) -> None:
        self.ctx.set_recording_paused(self.ctx.recording_state is RecorderState.RUNNING)
        self.refresh()

    def _idle_changed(self, minutes: int) -> None:
        self.ctx.set_idle_threshold(minutes * 60)

    def _autostart_toggled(self, on: bool) -> None:
        try:
            self.ctx.set_autostart(on)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("Start at sign-in"),
                tr("Could not change the sign-in startup entry: {p0}", p0=exc),
            )
        self.refresh()

    def _toggle_recording(self) -> None:
        if self.ctx.recording_consent:
            self.ctx.set_flag("consent.recording", False)
            self.ctx.stop_recording()
        elif ask_recording_consent(self):
            self.ctx.set_flag("consent.recording", True)
            self.ctx.start_recording()
        self.refresh()

    def _toggle_activity(self) -> None:
        if self.ctx.activity_consent:
            self.ctx.set_activity_consent(False)
        else:
            self.ctx.set_activity_consent(ask_activity_consent(self))
        self.refresh()

    def _toggle_camera(self) -> None:
        if self.ctx.camera_consent:
            self.ctx.set_camera_consent(False)
        else:
            self.ctx.set_camera_consent(ask_camera_consent(self))
        self.refresh()
        self.dataChanged.emit()

    def _device_changed(self, index: int) -> None:
        if index >= 0:
            self.ctx.set_setting("camera.index", str(index))

    def _open_data_dir(self) -> None:
        self.ctx.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.data_dir)))

    def _apply_retention(self) -> None:
        days = self.retention.value()
        self.ctx.set_setting("privacy.retention_days", str(days))
        with self.ctx.service.lock:
            removed = apply_retention(self.ctx.service.repository, days)
        QMessageBox.information(
            self,
            tr("Retention period"),
            tr(
                "Applied. Deleted {p0} old sessions and activity records from the same period.",
                p0=removed,
            ),
        )
        self.dataChanged.emit()

    def _export_all(self, kind: str) -> None:
        name, suffix = {
            "json": ("focuslab-export", "json"),
            "csv": ("focuslab-export", "csv"),
            "activity": ("focuslab-activity", "csv"),
        }[kind]
        default = str(Path.home() / f"{name}.{suffix}")
        path, _ = QFileDialog.getSaveFileName(self, tr("Export all"), default, f"*.{suffix}")
        if not path:
            return
        exporter = {"json": export_json, "csv": export_csv, "activity": export_activity_csv}[kind]
        with self.ctx.service.lock:
            exporter(self.ctx.service.repository, Path(path))
        QMessageBox.information(self, tr("Export"), tr("Saved:\n{p0}", p0=path))

    def _delete_all(self) -> None:
        answer = QMessageBox.warning(
            self,
            tr("Delete all records"),
            tr(
                "Permanently delete all sessions, state records, automatic "
                "activity records, and corrections? Settings, consent, "
                "classification rules, and exclusions are kept.\nThis "
                "cannot be undone. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        recorder = self.ctx.recorder
        running = recorder is not None and recorder.state is RecorderState.RUNNING
        if running:  # flush and drop the open span first so nothing points at deleted rows
            recorder.pause()
        with self.ctx.service.lock:
            delete_all(self.ctx.service.repository)
        if running:
            recorder.resume()
        self.dataChanged.emit()
        QMessageBox.information(self, tr("Delete"), tr("All records have been deleted."))

    def _fetch_model(self) -> None:
        answer = QMessageBox.question(
            self,
            tr("Download face model"),
            tr(
                (
                    "Download the face landmark model (about 3.7 MB) from the "
                    "official MediaPipe repository and verify its SHA256.\n\n"
                    "{p0}\n\nApart from this download, FocusLab uses the network only "
                    "for update checks you request or turn on in Settings."
                ),
                p0=FACE_MODEL_URL,
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.model_button.setEnabled(False)
        self.model_state.setText(tr("Downloading…"))

        def work() -> None:
            try:
                path = fetch_face_model()
                self._signals.modelFetched.emit(f"ok:{path}")
            except Exception as exc:  # network/checksum errors are shown to the user
                self._signals.modelFetched.emit(f"error:{exc}")

        threading.Thread(target=work, daemon=True).start()

    def _model_fetched(self, message: str) -> None:
        self.model_button.setEnabled(True)
        if message.startswith("error:"):
            QMessageBox.warning(
                self, tr("Face model"), tr("Could not download: {p0}", p0=message[6:])
            )
        self.refresh()

    def check_updates(self, quiet: bool = False) -> None:
        """Ask GitHub for the latest release; quiet (startup) checks hide network errors."""
        self._quiet_check = quiet
        self.update_check.setEnabled(False)
        self.update_state.setText(tr("Checking…"))

        def work() -> None:
            try:
                self._signals.updateChecked.emit(updater.latest_release())
            except urllib.error.HTTPError as exc:
                self._signals.updateChecked.emit(None if exc.code == 404 else exc)
            except Exception as exc:  # offline, timeout, unexpected response
                self._signals.updateChecked.emit(exc)

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, result: object) -> None:
        self.update_check.setEnabled(True)
        if isinstance(result, Exception):
            self.update_state.setText(
                "" if self._quiet_check else tr("Could not check: {p0}", p0=result)
            )
            return
        newer = isinstance(result, updater.Release) and updater.is_newer(result)
        self._release = result if newer else None
        self.update_button.setVisible(newer)
        if newer:
            self.update_state.setText(tr("FocusLab {p0} is available.", p0=result.version))
            self.updateAvailable.emit(result.version)
        elif result is None:
            self.update_state.setText(tr("No release has been published yet."))
        else:
            self.update_state.setText(tr("You have the latest version."))

    def start_update(self) -> None:
        "One click: download, verify and unpack with a progress window, then restart."
        release = self._release
        if release is None or self._update_dialog is not None:
            return
        if self._staged is not None and self._staged.is_dir():  # restart declined earlier
            self.restartForUpdate.emit(self._staged)
            return
        if not (updater.can_self_update() and release.zip_url and release.sha256_url):
            # Source checkouts (and releases without a Windows package) update by hand.
            QDesktopServices.openUrl(QUrl(release.page_url))
            return
        self.update_button.setEnabled(False)
        self.update_check.setEnabled(False)
        self.update_state.setText(tr("Downloading…"))
        dialog = UpdateDialog(release, self.window())
        dialog.ready.connect(self._update_ready)
        dialog.failed.connect(
            lambda exc: self.update_state.setText(tr("Could not update: {p0}", p0=exc))
        )
        dialog.cancelled.connect(lambda: self.update_state.setText(tr("Update cancelled.")))
        dialog.finished.connect(self._update_dialog_closed)
        self._update_dialog = dialog
        dialog.start()

    def _update_dialog_closed(self) -> None:
        self._update_dialog = None
        self.update_button.setEnabled(True)
        self.update_check.setEnabled(True)

    def _update_ready(self, staged: Path) -> None:
        self._staged = staged
        self.update_state.setText(tr("Update ready. FocusLab restarts to finish it."))
        self.restartForUpdate.emit(staged)

    def _calibrate(self) -> None:
        dialog = CalibrationDialog(self.ctx.camera_index, self)
        if dialog.exec() and dialog.result_calibration:
            self.ctx.set_setting("camera.calibration", dialog.result_calibration.to_json())
        self.refresh()

    def _reset_calibration(self) -> None:
        self.ctx.set_setting("camera.calibration", None)
        self.refresh()


def _row(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    for w in widgets:
        layout.addWidget(w)
    layout.addStretch()
    return holder
