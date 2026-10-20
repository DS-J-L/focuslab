"Reports: last 7 days, session list, per-session metrics, timeline, reasons and corrections."

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from focuslab.config import MODE_LABELS
from focuslab.domain.events import StateSegment
from focuslab.domain.models import FocusState, SessionStatus
from focuslab.focus.metrics import format_duration, format_ratio
from focuslab.focus.reasons import describe
from focuslab.i18n import LocalizedMapping, tr
from focuslab.services.export_service import (
    SessionReport,
    daily_totals,
    export_csv,
    export_json,
    session_report,
)
from focuslab.services.session_service import ACTIVE
from focuslab.ui.context import AppContext
from focuslab.ui.theme import (
    CORRECTION_LABELS,
    SELF_REPORT_LABELS,
    SHORT_LABELS,
    STATE_COLORS,
    STATE_LABELS,
)
from focuslab.ui.widgets import Legend, StatCard, TimelineWidget, WeekChart, clock_text

STATUS_TEXT = LocalizedMapping(
    {
        SessionStatus.FINISHED: "Completed",
        SessionStatus.INTERRUPTED: "Interrupted (recovered after an unclean exit)",
        SessionStatus.RUNNING: "In progress",
        SessionStatus.PAUSED: "Paused",
    }
)


def _local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone()


class ReportPage(QWidget):
    dataChanged = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self._report: SessionReport | None = None
        self._rows: list[StateSegment] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(QLabel(tr("Reports"), objectName="PageTitle"))

        week = QFrame(objectName="Card")
        week_layout = QVBoxLayout(week)
        week_layout.addWidget(
            QLabel(
                tr("Time by state over the last 7 days (with corrections)"), objectName="CardTitle"
            )
        )
        self.week = WeekChart()
        week_layout.addWidget(self.week)
        week_layout.addWidget(Legend())
        root.addWidget(week)

        self.sessions = QTableWidget(0, 4)
        self.sessions.setHorizontalHeaderLabels(
            [tr("Start"), tr("Goal"), tr("Measure"), tr("Task-related share")]
        )
        self.sessions.verticalHeader().setVisible(False)
        self.sessions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sessions.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sessions.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sessions.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sessions.itemSelectionChanged.connect(self._session_selected)
        self.sessions.setFixedHeight(190)
        root.addWidget(self.sessions)
        root.addWidget(self._build_detail(), 1)

    def _build_detail(self) -> QWidget:
        detail = QWidget()
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head_col = QVBoxLayout()
        self.detail_title = QLabel(tr("Select a session"))
        self.detail_title.setStyleSheet("font-size:18px; font-weight:700;")
        self.detail_sub = QLabel("", objectName="Muted", wordWrap=True)
        head_col.addWidget(self.detail_title)
        head_col.addWidget(self.detail_sub)
        head.addLayout(head_col, 1)
        head.addWidget(QLabel(tr("Goal achievement (self-report)")))
        self.self_report = QComboBox()
        self.self_report.addItem(tr("Not reported"), None)
        for key, text in SELF_REPORT_LABELS.items():
            self.self_report.addItem(text, key)
        self.self_report.currentIndexChanged.connect(self._self_report_changed)
        head.addWidget(self.self_report)
        layout.addLayout(head)

        cards = QGridLayout()
        self.cards = {
            "on": StatCard(tr("Estimated task-related time"), hint=tr("Cumulative ON_TASK")),
            "off": StatCard(tr("Possibly off-task time")),
            "away": StatCard(tr("Away / break")),
            "unknown": StatCard(tr("Cannot determine")),
            "ratio": StatCard(
                tr("Estimated task-related activity share"),
                hint=tr("Task-related ÷ (task-related + possibly off task)"),
            ),
            "return": StatCard(tr("Time from the end of a deviation until returning to work")),
            "switch": StatCard(tr("App switches")),
            "streak": StatCard(tr("Longest task-related streak")),
        }
        for i, card in enumerate(self.cards.values()):
            cards.addWidget(card, i // 4, i % 4)
        layout.addLayout(cards)
        self.notice = QLabel(
            tr(
                "Metrics estimate observable behavior. They do not measure attention, learning "
                "outcomes, or medical status."
            ),
            objectName="Notice",
            wordWrap=True,
        )
        layout.addWidget(self.notice)

        self.timeline = TimelineWidget(44)
        self.timeline.segmentClicked.connect(self._timeline_clicked)
        layout.addWidget(self.timeline)

        table_head = QHBoxLayout()
        table_head.addWidget(
            QLabel(tr("Interval estimates and evidence"), styleSheet="font-weight:700;")
        )
        table_head.addStretch()
        self.show_all = QCheckBox(tr("Also show task-related intervals"))
        self.show_all.toggled.connect(self._fill_segments)
        table_head.addWidget(self.show_all)
        layout.addLayout(table_head)
        self.segments = QTableWidget(0, 6)
        self.segments.setHorizontalHeaderLabels(
            [tr("Time"), tr("Duration"), tr("Estimate"), tr("Correct"), tr("Evidence"), tr("App")]
        )
        self.segments.verticalHeader().setVisible(False)
        self.segments.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.segments.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.segments.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.segments.setWordWrap(True)
        self.segments.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.segments.itemSelectionChanged.connect(self._segment_selected)
        self.segments.setMinimumHeight(260)
        layout.addWidget(self.segments, 1)

        correct = QHBoxLayout()
        correct.addWidget(QLabel(tr("Classify selected interval as")))
        self.correct_label = QComboBox()
        for label, text in CORRECTION_LABELS.items():
            self.correct_label.addItem(text, label)
        correct.addWidget(self.correct_label)
        self.apply_correction = QPushButton(tr("Correct"))
        self.apply_correction.clicked.connect(self._apply_correction)
        self.clear_correction = QPushButton(tr("Clear correction"))
        self.clear_correction.clicked.connect(self._clear_correction)
        correct.addWidget(self.apply_correction)
        correct.addWidget(self.clear_correction)
        correct.addStretch()
        self.export_json = QPushButton(tr("Export JSON"))
        self.export_json.clicked.connect(lambda: self._export("json"))
        self.export_csv = QPushButton(tr("Export CSV"))
        self.export_csv.clicked.connect(lambda: self._export("csv"))
        self.delete_button = QPushButton(tr("Delete session"), objectName="Danger")
        self.delete_button.clicked.connect(self._delete)
        for b in (self.export_json, self.export_csv, self.delete_button):
            correct.addWidget(b)
        layout.addLayout(correct)
        self._set_detail_enabled(False)
        return detail

    def _set_detail_enabled(self, on: bool) -> None:
        for w in (
            self.self_report,
            self.apply_correction,
            self.clear_correction,
            self.export_json,
            self.export_csv,
            self.delete_button,
            self.correct_label,
        ):
            w.setEnabled(on)

    # data -------------------------------------------------------------------------
    def refresh(self, select_id: int | None = None) -> None:
        if select_id is None and self._report:
            select_id = self._report.record.id
        with self.ctx.service.lock:
            repo = self.ctx.service.repository
            self.week.set_days(daily_totals(repo, 7))
            sessions = repo.list_sessions(limit=200)
            reports = {s.id: session_report(repo, s.id) for s in sessions}
        self.sessions.blockSignals(True)
        self.sessions.setRowCount(len(sessions))
        selected_row = None
        for row, s in enumerate(sessions):
            m = reports[s.id].metrics
            cells = [
                _local(s.started_at_utc).strftime("%m/%d %H:%M"),
                s.goal
                + ("" if s.status is SessionStatus.FINISHED else f" · {STATUS_TEXT[s.status]}"),
                format_duration(m.measured_s),
                format_ratio(m.on_task_ratio),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, s.id)
                self.sessions.setItem(row, col, item)
            if s.id == select_id:
                selected_row = row
        self.sessions.resizeColumnToContents(0)
        self.sessions.blockSignals(False)
        if selected_row is None and sessions:
            selected_row = 0
        if selected_row is not None:
            self.sessions.selectRow(selected_row)
            self._show(reports[sessions[selected_row].id])
        else:
            self._show(None)

    def show_session(self, session_id: int) -> None:
        self.refresh(select_id=session_id)

    def _session_selected(self) -> None:
        items = self.sessions.selectedItems()
        if not items:
            return
        session_id = items[0].data(Qt.ItemDataRole.UserRole)
        with self.ctx.service.lock:
            self._show(session_report(self.ctx.service.repository, session_id))

    def _show(self, report: SessionReport | None) -> None:
        self._report = report
        self._set_detail_enabled(report is not None)
        if report is None:
            self.detail_title.setText(tr("Select a session"))
            self.detail_sub.setText(tr("Start a session from Home to create your first record."))
            self.timeline.set_segments(())
            self.segments.setRowCount(0)
            return
        r, m = report.record, report.metrics
        started = _local(r.started_at_utc)
        ended = _local(r.ended_at_utc).strftime("%H:%M") if r.ended_at_utc else tr("In progress")
        camera = tr("Camera + PC activity") if r.camera_enabled else tr("PC activity only")
        self.detail_title.setText(r.goal)
        self.detail_sub.setText(
            tr(
                (
                    "{p0:%Y-%m-%d %H:%M}–{p1} · {p2} · {p3} · {p4} · Observed {p5}, paused {p6} · "
                    "Rules {p7}"
                ),
                p0=started,
                p1=ended,
                p2=MODE_LABELS[r.mode],
                p3=camera,
                p4=STATUS_TEXT[r.status],
                p5=format_duration(m.measured_s),
                p6=format_duration(r.paused_seconds),
                p7=r.rule_version,
            )
        )
        self.self_report.blockSignals(True)
        self.self_report.setCurrentIndex(max(0, self.self_report.findData(r.self_report)))
        self.self_report.blockSignals(False)

        s = m.seconds
        self.cards["on"].set(format_duration(s[FocusState.ON_TASK]))
        self.cards["off"].set(
            format_duration(s[FocusState.POSSIBLY_OFF_TASK]),
            tr("{p0} times", p0=m.off_task_episodes),
        )
        self.cards["away"].set(
            format_duration(s[FocusState.AWAY]),
            tr("Break {p0}", p0=format_duration(s[FocusState.BREAK])),
        )
        self.cards["unknown"].set(
            format_duration(s[FocusState.UNKNOWN]),
            tr("Observation coverage {p0}", p0=format_ratio(m.coverage)),
        )
        self.cards["ratio"].set(format_ratio(m.on_task_ratio))
        self.cards["return"].set(
            format_duration(m.mean_return_gap_s) if m.return_gaps_s else tr("No return recorded"),
            tr(
                "Average possible deviation {p0} · Ended without returning: {p1} times",
                p0=format_duration(m.mean_off_task_s),
                p1=m.episodes_without_return,
            ),
        )
        self.cards["switch"].set(tr("{p0} times", p0=m.app_switches))
        self.cards["streak"].set(
            format_duration(m.longest_on_task_s),
            tr("Corrected intervals: {p0}", p0=m.corrected_segments),
        )
        self.timeline.set_segments(report.segments, m.measured_s)
        self._fill_segments()

    def _fill_segments(self) -> None:
        report = self._report
        if report is None:
            return
        show_all = self.show_all.isChecked()
        self._rows = [
            seg
            for seg in report.segments
            if show_all or seg.state is not FocusState.ON_TASK or seg.corrected_label
        ]
        self.segments.setRowCount(len(self._rows))
        for row, seg in enumerate(self._rows):
            judged = QTableWidgetItem(STATE_LABELS[seg.state])
            judged.setForeground(Qt.GlobalColor.black)
            judged.setBackground(_tint(STATE_COLORS[seg.state]))
            cells = [
                QTableWidgetItem(f"{clock_text(seg.start_s)}–{clock_text(seg.end_s)}"),
                QTableWidgetItem(format_duration(seg.duration_s)),
                judged,
                QTableWidgetItem(SHORT_LABELS[seg.corrected_label] if seg.corrected_label else ""),
                QTableWidgetItem(" · ".join(describe(seg.reason_codes))),
                QTableWidgetItem(", ".join(seg.app_names)),
            ]
            for col, item in enumerate(cells):
                self.segments.setItem(row, col, item)
        self.segments.resizeColumnToContents(0)
        self.segments.resizeColumnToContents(2)
        self.segments.resizeRowsToContents()

    def _selected_segment(self) -> StateSegment | None:
        rows = self.segments.selectionModel().selectedRows()
        return self._rows[rows[0].row()] if rows else None

    def _segment_selected(self) -> None:
        seg = self._selected_segment()
        if seg and self._report:
            self.timeline.set_segments(
                self._report.segments, self._report.metrics.measured_s, seg.event_id
            )

    def _timeline_clicked(self, seg: StateSegment) -> None:
        if seg not in self._rows:
            self.show_all.setChecked(True)
        for row, candidate in enumerate(self._rows):
            if candidate.event_id == seg.event_id:
                self.segments.selectRow(row)
                break

    # actions ----------------------------------------------------------------------
    def _reload_current(self) -> None:
        if self._report:
            self.refresh(select_id=self._report.record.id)
        self.dataChanged.emit()

    def _apply_correction(self) -> None:
        seg = self._selected_segment()
        if seg is None or seg.event_id is None:
            return
        with self.ctx.service.lock:
            label = FocusState(self.correct_label.currentData())
            self.ctx.service.repository.set_feedback(seg.event_id, label)
        self._reload_current()

    def _clear_correction(self) -> None:
        seg = self._selected_segment()
        if seg is None or seg.event_id is None:
            return
        with self.ctx.service.lock:
            self.ctx.service.repository.clear_feedback(seg.event_id)
        self._reload_current()

    def _self_report_changed(self) -> None:
        if self._report:
            self.ctx.service.set_self_report(self._report.record.id, self.self_report.currentData())

    def _export(self, kind: str) -> None:
        if not self._report:
            return
        sid = self._report.record.id
        default = str(Path.home() / f"focuslab-session-{sid}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, tr("Export"), default, f"*.{kind}")
        if not path:
            return
        with self.ctx.service.lock:
            repo = self.ctx.service.repository
            (export_json if kind == "json" else export_csv)(repo, Path(path), [sid])
        QMessageBox.information(self, tr("Export"), tr("Saved:\n{p0}", p0=path))

    def _delete(self) -> None:
        report = self._report
        if report is None:
            return
        snap = self.ctx.service.snapshot()
        if snap.session_id == report.record.id and snap.lifecycle in ACTIVE:
            QMessageBox.warning(
                self, tr("Cannot delete"), tr("End the running session before deleting it.")
            )
            return
        answer = QMessageBox.question(
            self,
            tr("Delete session"),
            tr(
                "Delete all records and corrections for session '{p0}'?\nThis cannot be undone.",
                p0=report.record.goal,
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with self.ctx.service.lock:
            self.ctx.service.repository.delete_session(report.record.id)
        self._report = None
        self.refresh()
        self.dataChanged.emit()


def _tint(hex_color: str) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(70)
    return color
