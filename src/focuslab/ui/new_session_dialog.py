"New session popup opened from Home's (+) button: goal, mode, time, allowed apps, camera."

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.windows_tracker import normalize, visible_window_apps
from focuslab.config import MODE_LABELS, NEUTRAL_APPS
from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.i18n import LocalizedMapping, tr
from focuslab.ui.context import AppContext
from focuslab.ui.theme import style_form

MODE_HINTS = LocalizedMapping(
    {
        SessionMode.CODING: (
            "IDE, terminal, and documentation. Looking away alone does not establish task "
            "deviation."
        ),
        SessionMode.LECTURE: "Video lectures. No keyboard or mouse input is expected.",
        SessionMode.READING_WRITING: (
            "Paper books and notes. Looking down is treated as work, with a longer wait "
            "before estimating time away."
        ),
        SessionMode.CUSTOM: "Choose allowed apps yourself.",
    }
)


class NewSessionDialog(QDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("New session"))
        self.setMinimumWidth(560)
        self.resize(600, 640)  # the whole form without scrolling
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 16)
        scroll = QScrollArea()  # the window may be only 680 px tall
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        content = QWidget(objectName="PageContent")
        scroll.setWidget(content)
        form = QFormLayout(content)
        style_form(form)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setVerticalSpacing(10)
        form.setContentsMargins(24, 20, 24, 8)

        self.goal = QLineEdit(ctx.setting("last.goal", "") or "")
        self.goal.setPlaceholderText(tr("For example: solve algorithm problems"))
        form.addRow(tr("Goal"), self.goal)

        self.mode = QComboBox()
        for mode in SessionMode:
            self.mode.addItem(MODE_LABELS[mode], mode)
        last_mode = ctx.setting("last.mode", SessionMode.CODING.value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(SessionMode(last_mode))))
        self.mode_hint = QLabel(objectName="Muted")
        self.mode_hint.setWordWrap(True)
        form.addRow(tr("Work mode"), self.mode)
        form.addRow("", self.mode_hint)

        self.minutes = QSpinBox()
        self.minutes.setRange(0, 240)
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(tr(" min"))
        self.minutes.setSpecialValueText(tr("No time limit"))
        self.minutes.setValue(int(ctx.setting("last.minutes", "25") or 25))
        form.addRow(tr("Target time"), self.minutes)

        self.apps = QListWidget()
        self.apps.setMinimumHeight(90)
        self.apps.setMaximumHeight(130)
        self.apps.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        app_buttons = QHBoxLayout()
        app_buttons.setSpacing(8)
        add = QPushButton(tr("Add manually…"))
        add.clicked.connect(self._add_app_manual)
        self.add_open = QPushButton(tr("Add from open apps…"))
        self.add_open.clicked.connect(self._add_app_from_open)
        remove = QPushButton(tr("Remove selected"))
        remove.clicked.connect(self._remove_apps)
        reset = QPushButton(tr("Defaults"))
        reset.clicked.connect(self._reset_apps)
        for b in (add, self.add_open, remove, reset):
            b.setAutoDefault(False)  # Enter in the goal field starts, not "Add manually"
            app_buttons.addWidget(b)
        app_buttons.addStretch()
        apps_col = QVBoxLayout()
        apps_col.setSpacing(10)
        apps_col.addWidget(self.apps)
        apps_col.addLayout(app_buttons)
        note = QLabel(
            tr(
                "Matches process names (for example, code.exe). With the "
                "browser extension connected, add a site such as "
                "github.com to allow the browser only on that site."
            ),
            objectName="Muted",
        )
        note.setWordWrap(True)
        apps_col.addWidget(note)
        form.addRow(tr("Allowed apps"), apps_col)

        self.camera = QCheckBox(tr("Observe face presence and head pose with a webcam (optional)"))
        self.camera.setChecked(ctx.flag("last.camera", False))
        form.addRow(tr("Camera"), self.camera)

        # Cancel, then Start, on every platform (a button box would reorder them on Windows).
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.reject)
        self.start_button = QPushButton(tr("Start"), objectName="Primary")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.setContentsMargins(24, 12, 24, 0)
        row.setSpacing(8)
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        outer.addLayout(row)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def current_mode(self) -> SessionMode:
        return SessionMode(self.mode.currentData())

    def _mode_changed(self) -> None:
        mode = self.current_mode()
        self.mode_hint.setText(MODE_HINTS[mode])
        self._set_apps(self.ctx.allowed_apps(mode))

    def _set_apps(self, apps) -> None:
        self.apps.clear()
        for app in sorted(set(map(normalize, apps))):
            self.apps.addItem(app)

    def _current_apps(self) -> tuple[str, ...]:
        return tuple(self.apps.item(i).text() for i in range(self.apps.count()))

    def _save_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), self._current_apps())

    def _add(self, name: str) -> None:
        name = normalize(name)
        if name and name not in self._current_apps():
            self.apps.addItem(name)
            self.apps.sortItems()
            self._save_apps()

    def _add_app_manual(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("Add allowed app"), tr("Process name (for example, code.exe)")
        )
        if ok:
            self._add(name)

    def _add_app_from_open(self) -> None:
        menu = QMenu(self)
        names = [n for n in visible_window_apps() if normalize(n) not in NEUTRAL_APPS]
        for name in names:
            menu.addAction(name, lambda n=name: self._add(n))
        if not names:
            menu.addAction(tr("No open apps found")).setEnabled(False)
        menu.exec(self.add_open.mapToGlobal(self.add_open.rect().bottomLeft()))

    def _remove_apps(self) -> None:
        for item in self.apps.selectedItems():
            self.apps.takeItem(self.apps.row(item))
        self._save_apps()

    def _reset_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), None)
        self._set_apps(self.ctx.allowed_apps(self.current_mode()))

    def accept(self) -> None:
        "Start: confirm an empty allow list, remember the choices, then close."
        if not self._current_apps():
            answer = QMessageBox.question(
                self,
                tr("No allowed apps"),
                tr("With an empty allow list, every app will be treated as not allowed. Continue?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        cfg = self.config()
        self.ctx.set_setting("last.goal", cfg.goal)
        self.ctx.set_setting("last.mode", cfg.mode.value)
        self.ctx.set_setting("last.minutes", str(cfg.planned_minutes))
        self.ctx.set_flag("last.camera", cfg.camera_enabled)
        super().accept()

    def config(self) -> SessionConfig:
        goal = self.goal.text().strip() or tr("Focus session")
        return SessionConfig(
            goal,
            self.current_mode(),
            self.minutes.value(),
            self._current_apps(),
            self.camera.isChecked(),
        )
