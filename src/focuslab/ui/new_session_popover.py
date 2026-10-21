"""New session settings in a speech bubble above Home's (+): goal, mode, time, allowed apps,
camera. It is part of the page, not a separate window, so Home stays visible behind it."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
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

BUBBLE_WIDTH = 460
RADIUS = 12
TAIL = 10  # height of the tail pointing at the (+)
SHADOW = 12  # transparent margin the soft shadow is painted into
GAP = 8  # between the tail tip and the (+)
EDGE = 16  # closest the bubble comes to the page's top and left edges
SLIDE = 12  # the bubble rises this far while fading in
ANIMATION_MS = 160


class NewSessionForm(QWidget):
    "The session settings. Allowed apps sit behind a one-line summary until opened."

    sizeChanged = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent, objectName="PopoverContent")
        self.ctx = ctx
        form = QFormLayout(self)
        style_form(form)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setVerticalSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

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

        self.apps_toggle = QPushButton(objectName="Disclosure")
        self.apps_toggle.clicked.connect(lambda: self.show_apps(not self.apps_panel.isVisible()))
        self.apps_panel = QWidget()
        self.apps_panel.hide()
        panel = QVBoxLayout(self.apps_panel)
        panel.setContentsMargins(0, 4, 0, 0)
        panel.setSpacing(8)
        self.apps = QListWidget()
        self.apps.setMinimumHeight(90)
        self.apps.setMaximumHeight(130)
        self.apps.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        panel.addWidget(self.apps)
        manual = QHBoxLayout()
        manual.setSpacing(8)
        self.manual_app = QLineEdit()
        self.manual_app.setPlaceholderText(tr("Process name (for example, code.exe)"))
        self.manual_app.returnPressed.connect(self._add_app_manual)
        add = QPushButton(tr("Add"))
        add.clicked.connect(self._add_app_manual)
        manual.addWidget(self.manual_app, 1)
        manual.addWidget(add)
        panel.addLayout(manual)
        app_buttons = QHBoxLayout()
        app_buttons.setSpacing(8)
        self.add_open = QPushButton(tr("Add from open apps…"))
        self.add_open.clicked.connect(self._add_app_from_open)
        remove = QPushButton(tr("Remove selected"))
        remove.clicked.connect(self._remove_apps)
        reset = QPushButton(tr("Defaults"))
        reset.clicked.connect(self._reset_apps)
        app_buttons.addWidget(self.add_open)
        app_buttons.addWidget(remove)
        app_buttons.addStretch()
        app_buttons.addWidget(reset)
        panel.addLayout(app_buttons)
        note = QLabel(
            tr(
                "Matches process names (for example, code.exe). With the "
                "browser extension connected, add a site such as "
                "github.com to allow the browser only on that site."
            ),
            objectName="Muted",
        )
        note.setWordWrap(True)
        panel.addWidget(note)
        apps_col = QVBoxLayout()
        apps_col.setSpacing(0)
        apps_col.addWidget(self.apps_toggle)
        apps_col.addWidget(self.apps_panel)
        form.addRow(tr("Allowed apps"), apps_col)

        self.camera = QCheckBox(tr("Use the webcam (optional)"))
        self.camera.setChecked(ctx.flag("last.camera", False))
        camera_hint = QLabel(tr("Observes face presence and head pose."), objectName="Muted")
        camera_hint.setWordWrap(True)
        camera_col = QVBoxLayout()
        camera_col.setSpacing(2)
        camera_col.addWidget(self.camera)
        camera_col.addWidget(camera_hint)
        form.addRow(tr("Camera"), camera_col)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def current_mode(self) -> SessionMode:
        return SessionMode(self.mode.currentData())

    def show_apps(self, shown: bool) -> None:
        self.apps_panel.setVisible(shown)
        self._update_apps_toggle()
        self.sizeChanged.emit()

    def _update_apps_toggle(self) -> None:
        count = self.apps.count()
        if self.apps_panel.isVisible():
            self.apps_toggle.setText(tr("{p0} allowed · Hide", p0=count))
        else:
            self.apps_toggle.setText(tr("{p0} allowed · Edit", p0=count))
        self.apps_toggle.setToolTip(", ".join(self._current_apps()))

    def _mode_changed(self) -> None:
        mode = self.current_mode()
        self.mode_hint.setText(MODE_HINTS[mode])
        self._set_apps(self.ctx.allowed_apps(mode))
        self.sizeChanged.emit()  # the hint may wrap onto more lines

    def _set_apps(self, apps) -> None:
        self.apps.clear()
        for app in sorted(set(map(normalize, apps))):
            self.apps.addItem(app)
        self._update_apps_toggle()

    def _current_apps(self) -> tuple[str, ...]:
        return tuple(self.apps.item(i).text() for i in range(self.apps.count()))

    def _save_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), self._current_apps())
        self._update_apps_toggle()

    def _add(self, name: str) -> None:
        name = normalize(name)
        if name and name not in self._current_apps():
            self.apps.addItem(name)
            self.apps.sortItems()
            self._save_apps()

    def _add_app_manual(self) -> None:
        self._add(self.manual_app.text())
        self.manual_app.clear()

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

    def commit(self) -> SessionConfig | None:
        "Start: confirm an empty allow list, remember the choices; None if declined."
        if not self._current_apps():
            answer = QMessageBox.question(
                self,
                tr("No allowed apps"),
                tr("With an empty allow list, every app will be treated as not allowed. Continue?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        cfg = self.config()
        self.ctx.set_setting("last.goal", cfg.goal)
        self.ctx.set_setting("last.mode", cfg.mode.value)
        self.ctx.set_setting("last.minutes", str(cfg.planned_minutes))
        self.ctx.set_flag("last.camera", cfg.camera_enabled)
        return cfg

    def config(self) -> SessionConfig:
        goal = self.goal.text().strip() or tr("Focus session")
        return SessionConfig(
            goal,
            self.current_mode(),
            self.minutes.value(),
            self._current_apps(),
            self.camera.isChecked(),
        )


class NewSessionPopover(QWidget):
    """A bubble over the page whose tail points at `anchor` (the (+)). Esc, Cancel, or a click
    elsewhere on the window closes it; it then deletes itself."""

    started = Signal(object)  # SessionConfig
    dismissed = Signal()

    def __init__(self, ctx: AppContext, anchor: QWidget, parent: QWidget) -> None:
        super().__init__(parent)
        self.anchor = anchor
        self.setAccessibleName(tr("New session"))
        self._open = False
        self._target = QRect()
        self._tip_x = 0.0
        self._animation: QParallelAnimationGroup | None = None
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW + 20, SHADOW + 16, SHADOW + 20, SHADOW + TAIL + 16)
        outer.setSpacing(12)
        outer.addWidget(QLabel(tr("New session"), objectName="PopoverTitle"))
        self.form = NewSessionForm(ctx)
        self.form.sizeChanged.connect(self._form_resized)
        self.scroll = QScrollArea(objectName="PopoverScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setWidget(self.form)
        outer.addWidget(self.scroll, 1)

        # Cancel, then Start, on every platform.
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.clicked.connect(lambda: self.dismiss())
        self.start_button = QPushButton(tr("Start"), objectName="Primary")
        self.start_button.clicked.connect(self._start)
        self.form.goal.returnPressed.connect(self._start)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.start_button)
        outer.addLayout(row)

    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self.place()
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)
        self.form.goal.setFocus()
        self.form.goal.selectAll()
        self._animate(opening=True)

    def dismiss(self, animated: bool = True) -> None:
        if not self._open:
            return
        self._open = False
        QApplication.instance().removeEventFilter(self)
        focused = QApplication.focusWidget()
        if focused is not None and self.isAncestorOf(focused):
            self.anchor.setFocus()
        self.dismissed.emit()
        if animated and self.isVisible():
            self._animate(opening=False)
        else:
            self._closed()

    def _start(self) -> None:
        config = self.form.commit()
        if config is not None:
            self.dismiss(animated=False)
            self.started.emit(config)

    # geometry and painting ------------------------------------------------------------------
    def _form_resized(self) -> None:
        self.place()
        if self.form.apps_panel.isVisible():  # once laid out, bring the opened list into view
            QTimer.singleShot(0, self, self._reveal_apps)

    def _reveal_apps(self) -> None:
        self.scroll.ensureWidgetVisible(self.form.apps_panel)
        self.scroll.horizontalScrollBar().setValue(0)  # scroll down only, never sideways

    def place(self) -> None:
        "Right-aligned with the anchor, just above it, as tall as the form needs (scrolls beyond)."
        page = self.parentWidget()
        anchor = self.anchor.geometry()
        width = min(BUBBLE_WIDTH, page.width() - 2 * EDGE) + 2 * SHADOW
        margins = self.layout().contentsMargins()
        self.form.layout().invalidate()
        form_height = self.form.heightForWidth(width - margins.left() - margins.right())
        if form_height < 0:
            form_height = self.form.sizeHint().height()
        wanted = (
            self.layout().sizeHint().height() - self.scroll.sizeHint().height() + form_height + 2
        )
        bottom = anchor.top() - GAP + SHADOW
        top = max(EDGE - SHADOW, bottom - wanted)
        left = max(0, anchor.right() + 1 + SHADOW - width)
        self._target = QRect(left, top, width, bottom - top)
        self._tip_x = anchor.center().x() + 0.5 - left
        if self._animation is None:
            self.setGeometry(self._target)
        else:
            self.resize(self._target.size())
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW - TAIL)
        tip = min(max(self._tip_x, body.left() + RADIUS + TAIL), body.right() - RADIUS - TAIL)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        tail = QPainterPath()
        tail.moveTo(tip - TAIL, body.bottom() - 1)
        tail.lineTo(tip, body.bottom() + TAIL)
        tail.lineTo(tip + TAIL, body.bottom() - 1)
        tail.closeSubpath()
        path = path.united(tail)
        shadow = path.translated(0, 3)
        for spread in range(SHADOW, 0, -2):  # wide faint strokes first: a soft edge
            painter.strokePath(shadow, QPen(QColor(31, 36, 48, 7), spread))
        painter.fillPath(path, QColor("white"))
        painter.strokePath(path, QPen(QColor("#E3E6EC"), 1))

    # animation ----------------------------------------------------------------------------------
    def _animate(self, opening: bool) -> None:
        if self._animation is not None:
            self._animation.stop()  # reversing mid-way starts from where it is now
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0 if opening else 1.0)
        self.setGraphicsEffect(effect)
        resting = self._target.topLeft()
        lowered = resting + QPoint(0, SLIDE)
        fade = QPropertyAnimation(effect, b"opacity")
        fade.setEndValue(1.0 if opening else 0.0)
        slide = QPropertyAnimation(self, b"pos")
        slide.setStartValue(self.pos() if self._animation else lowered if opening else resting)
        slide.setEndValue(resting if opening else lowered)
        group = QParallelAnimationGroup(self)
        for animation in (fade, slide):
            animation.setDuration(ANIMATION_MS)
            animation.setEasingCurve(
                QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic
            )
            group.addAnimation(animation)
        group.finished.connect(self._opened if opening else self._closed)
        self._animation = group
        group.start()

    def _opened(self) -> None:
        self._animation = None
        self.setGraphicsEffect(None)  # text is drawn directly again, not through a pixmap
        self.place()

    def _closed(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self.hide()
        self.deleteLater()

    # closing ------------------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        "A press elsewhere in this window closes the bubble and still reaches its target."
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(watched, QWidget)
            and watched.window() is self.window()
            and not (watched is self or self.isAncestorOf(watched))
            and not (watched is self.anchor or self.anchor.isAncestorOf(watched))
        ):
            self.dismiss()
        return False
