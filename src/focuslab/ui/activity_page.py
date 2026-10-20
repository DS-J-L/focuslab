"""Activity: what the always-on recorder saw — today's overview, the day timeline with
classification and webcam observations, automatic sessions, and day/week/month statistics."""

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.auto_sessions import span_label
from focuslab.activity.classifier import CLASS_REASON_TEXT
from focuslab.activity.stats import ActivityStats, LabeledSpan, local_day_bounds
from focuslab.domain.activity import Category, ClassSource, SpanKind
from focuslab.focus.metrics import format_duration
from focuslab.i18n import LocalizedMapping, tr, weekday_name
from focuslab.ui.context import AppContext
from focuslab.ui.recording_status import WARNING_STYLE, RecordingHealth
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.theme import CATEGORY_COLORS, CATEGORY_LABELS
from focuslab.ui.widgets import Bar, BarTimeline, Legend, StackedBars, StatCard

KIND_TEXT = LocalizedMapping({SpanKind.IDLE: "Idle (no input)", SpanKind.LOCKED: "Screen locked"})
SOURCE_TEXT = LocalizedMapping(
    {
        ClassSource.RULE: "Built-in rule",
        ClassSource.USER_RULE: "My rule",
        ClassSource.USER: "Manual correction",
        ClassSource.SYSTEM: "Observed state",
    }
)
RANGES = {"Last 7 days": 7, "Last 30 days": 30}
DAY, RANGE = "activity.day", "activity.range"  # ActivityReporter keys
WORK_HINT = "Time classified as development, study, documentation, research, or productivity tools"
METRICS_NOTE = (
    "This page shows automatic recordings. Input-based active time reflects keyboard "
    "or mouse activity, so watching a lecture or reading without input may count as "
    "idle. Work-category time adds up development, study, documentation, research, "
    "and productivity tools. Estimated task-related time in focus-session reports "
    "uses the session goal, allowed apps, and camera observations, so the same "
    "period can have different values. For example, a document editor may count as "
    "work here but as possibly off task in a session if it is not an allowed app."
)


def _hm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def _dur(ms: float | None) -> str:
    return format_duration(None if ms is None else ms / 1000)


def _camera_text(item: LabeledSpan) -> str:
    ov = item.camera
    if ov is None:
        return ""
    if not ov.has_camera:
        return tr("Focus session (no camera)")
    parts = [
        tr("{p0} {p1}s", p0=label, p1=seconds)
        for label, seconds in (
            (tr("Away"), ov.away_s),
            (tr("Face not visible"), ov.face_absent_s),
            (tr("Looking away"), ov.head_away_s),
            (tr("Looking down"), ov.head_down_s),
        )
        if seconds
    ]
    return " · ".join(parts) or tr("Observed facing the screen")


def _table(headers: list[str], stretch: int) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table: QTableWidget, rows: list[list[str]], keys: list[object] | None = None) -> None:
    table.setRowCount(len(rows))
    for r, cells in enumerate(rows):
        for c, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if keys is not None:
                item.setData(Qt.ItemDataRole.UserRole, keys[r])
            table.setItem(r, c, item)
    table.resizeColumnsToContents()


class ActivityPage(QWidget):
    dataChanged = Signal()

    def __init__(self, ctx: AppContext, reporter: ActivityReporter) -> None:
        super().__init__()
        self.ctx = ctx
        self.reporter = reporter
        reporter.ready.connect(self._report_ready)
        reporter.failed.connect(self._report_failed)
        self.day = datetime.now().astimezone().date()
        self._labeled: list[LabeledSpan] = []
        self._rows: list[LabeledSpan] = []
        self.stats: ActivityStats | None = None

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
        root.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(QLabel(tr("Activity"), objectName="PageTitle"))
        self.loading = QLabel(objectName="Muted")
        head.addWidget(self.loading)
        self.status = QLabel(objectName="Muted", wordWrap=True)
        head.addWidget(self.status, 1)
        prev, nxt, today = QPushButton("◀"), QPushButton("▶"), QPushButton(tr("Today"))
        prev.clicked.connect(lambda: self.show_day(self.day - timedelta(days=1)))
        nxt.clicked.connect(lambda: self.show_day(self.day + timedelta(days=1)))
        today.clicked.connect(lambda: self.show_day(datetime.now().astimezone().date()))
        self.day_label = QLabel(styleSheet="font-weight:700; padding:0 8px;")
        for w in (prev, self.day_label, nxt, today):
            head.addWidget(w)
        root.addLayout(head)
        self.save_warning = QLabel(objectName="Notice", wordWrap=True)
        self.save_warning.setStyleSheet(WARNING_STYLE)
        self.save_warning.hide()
        root.addWidget(self.save_warning)

        cards = QGridLayout()
        self.cards = {
            "total": StatCard(
                tr("Total PC use"), hint=tr("Active + idle (excludes lock and sleep)")
            ),
            "active": StatCard(
                tr("Input-based active time"),
                hint=tr(
                    "Time with keyboard or mouse activity (viewing or reading "
                    "without input is idle)"
                ),
            ),
            "idle": StatCard(tr("Idle")),
            "switches": StatCard(tr("Task switches"), hint=tr("Changes between programs or sites")),
            "sessions": StatCard(
                tr("Automatic sessions"), hint=tr("Work intervals detected without a timer")
            ),
            "work": StatCard(tr("Work-category time"), hint=tr(WORK_HINT)),
        }
        for i, card in enumerate(self.cards.values()):
            cards.addWidget(card, i // 3, i % 3)
        root.addLayout(cards)
        self.metrics_note = QLabel(tr(METRICS_NOTE), objectName="Muted", wordWrap=True)
        root.addWidget(self.metrics_note)

        self.category_bar = BarTimeline(30)
        self.category_legend = QLabel(objectName="Muted", wordWrap=True)
        box = QGroupBox(tr("Time by category"))
        lay = QVBoxLayout(box)
        lay.addWidget(self.category_bar)
        lay.addWidget(self.category_legend)
        root.addWidget(box)

        box = QGroupBox(tr("Daily timeline"))
        lay = QVBoxLayout(box)
        self.timeline = BarTimeline(56)
        self.timeline.itemClicked.connect(self._timeline_clicked)
        lay.addWidget(self.timeline)
        lay.addWidget(Legend([(CATEGORY_COLORS[c], CATEGORY_LABELS[c]) for c in Category]))
        root.addWidget(box)

        tops = QHBoxLayout()
        self.top_apps = _table([tr("Program"), tr("Time"), tr("Share")], 0)
        self.top_sites = _table([tr("Site"), tr("Time"), tr("Share")], 0)
        for title, table in (
            (tr("Time by program"), self.top_apps),
            (tr("Time by website"), self.top_sites),
        ):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(table)
            table.setMinimumHeight(140)
            table.setMaximumHeight(260)
            tops.addWidget(box)
        root.addLayout(tops)

        root.addWidget(self._build_spans())

        box = QGroupBox(
            tr("Automatic sessions (overlapping focus sessions are marked; time is counted once)")
        )
        lay = QVBoxLayout(box)
        self.sessions = _table(
            [
                tr("Time"),
                tr("Work category"),
                tr("Active"),
                tr("Interrupted"),
                tr("Switches"),
                tr("Detours / returns"),
                tr("Main apps"),
                tr("Focus session"),
            ],
            6,
        )
        self.sessions.setMinimumHeight(120)
        self.sessions.setMaximumHeight(260)
        lay.addWidget(self.sessions)
        root.addWidget(box)

        root.addWidget(self._build_statistics())
        self.notice = QLabel(
            tr(
                "Records are estimates of observed PC use. Time away is "
                "subtracted from work only when the face is absent and "
                "there is no input. Looking away alone does not establish "
                "that you are off task."
            ),
            objectName="Notice",
            wordWrap=True,
        )
        root.addWidget(self.notice)

    # sections ---------------------------------------------------------------------
    def _build_spans(self) -> QGroupBox:
        box = QGroupBox(tr("Activity intervals"))
        lay = QVBoxLayout(box)
        top = QHBoxLayout()
        self.hide_short = QCheckBox(tr("Hide intervals shorter than 10 seconds"))
        self.hide_short.setChecked(True)
        self.hide_short.toggled.connect(self._fill_spans)
        top.addWidget(self.hide_short)
        top.addStretch()
        lay.addLayout(top)
        self.spans = _table(
            [
                tr("Start"),
                tr("End"),
                tr("Duration"),
                tr("Program"),
                tr("Site"),
                tr("Category"),
                tr("Confidence"),
                tr("Evidence"),
                tr("Camera observations"),
            ],
            7,
        )
        self.spans.setMinimumHeight(220)
        self.spans.setMaximumHeight(420)
        self.spans.itemSelectionChanged.connect(self._span_selected)
        lay.addWidget(self.spans)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Classify selected interval as")))
        self.correct_to = QComboBox()
        for category in Category:
            self.correct_to.addItem(CATEGORY_LABELS[category], category)
        row.addWidget(self.correct_to)
        self.always = QCheckBox(tr("Always apply to this app / site"))
        row.addWidget(self.always)
        self.apply_button = QPushButton(tr("Correct"))
        self.apply_button.clicked.connect(self._apply_correction)
        self.clear_button = QPushButton(tr("Clear correction"))
        self.clear_button.clicked.connect(self._clear_correction)
        row.addWidget(self.apply_button)
        row.addWidget(self.clear_button)
        row.addStretch()
        lay.addLayout(row)
        self._set_correction_enabled(False)
        return box

    def _build_statistics(self) -> QGroupBox:
        box = QGroupBox(tr("Statistics"))
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.range = QComboBox()
        for label, days in RANGES.items():
            self.range.addItem(tr(label), days)
        self.range.currentIndexChanged.connect(self.refresh_statistics)
        row.addWidget(QLabel(tr("Period")))
        row.addWidget(self.range)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel(tr("Daily time by category"), objectName="CardTitle"))
        self.daily = StackedBars(list(Category), CATEGORY_COLORS)
        lay.addWidget(self.daily)
        lay.addWidget(
            QLabel(tr("Input-based active time by hour (period total)"), objectName="CardTitle")
        )
        self.hourly = StackedBars(["active"], {"active": "#3B5BDB"}, label_every=3, height=120)
        lay.addWidget(self.hourly)
        self.range_summary = QLabel(wordWrap=True)
        self.range_summary.setStyleSheet("font-weight:400;")
        lay.addWidget(self.range_summary)
        return box

    # data -------------------------------------------------------------------------
    def show_day(self, day: date) -> None:
        self.day = min(day, datetime.now().astimezone().date())
        self.refresh()

    def auto_refresh(self) -> None:
        """Periodic update while the page is open: only today, never while the user has a
        span selected (about to correct it) or a load is still running, and without
        recomputing the long-range charts."""
        if (
            self.day == datetime.now().astimezone().date()
            and not self.spans.selectedItems()
            and not self.reporter.pending(DAY)
        ):
            self.refresh(statistics=False)

    @property
    def loading_now(self) -> bool:
        return self.reporter.pending(DAY) or self.reporter.pending(RANGE)

    def refresh(self, statistics: bool = True) -> None:
        """Ask the worker for the day (and the long-range charts). The page keeps showing
        the previous result, and stays usable, until the new one arrives."""
        start, end = local_day_bounds(self.day)
        self.day_label.setText(f"{self.day:%Y-%m-%d} ({weekday_name(self.day.weekday())})")
        self.set_recording_health(self.ctx.recording_health())
        self._set_correction_enabled(False)  # the rows may change under the selection
        self.reporter.request(DAY, start, end, (self.day, start, end))
        if statistics:
            self.refresh_statistics()
        self._show_loading()

    def refresh_statistics(self) -> None:
        days = self.range.currentData()
        first = self.day - timedelta(days=days - 1)
        start, _ = local_day_bounds(first)
        _, end = local_day_bounds(self.day)
        self.reporter.request(RANGE, start, end, (first, days))
        self._show_loading()

    def _show_loading(self, error: str | None = None) -> None:
        if error:
            self.loading.setText(tr("Could not load: {p0}", p0=error))
        else:
            self.loading.setText(tr("Loading…") if self.loading_now else "")

    def _report_ready(self, key: str, context, result) -> None:
        if key == DAY:
            day, start, end = context
            if day == self.day:
                self._labeled, self.stats = result
                self._fill_overview(self.stats)
                self._fill_timeline(start, end)
                self._fill_spans()
                self._fill_sessions(self.stats)
        elif key == RANGE:
            self._fill_statistics(*context, result[1])
        else:
            return
        self._show_loading()

    def _report_failed(self, key: str, context, message: str) -> None:
        if key in (DAY, RANGE):
            self._show_loading(message)

    def set_recording_health(self, health: RecordingHealth) -> None:
        "Observing and saving, separately; a failing save stays visible until a save works."
        self.status.setText(health.text)
        self.status.setStyleSheet(WARNING_STYLE if health.saving_failed else "")
        self.status.setToolTip(health.detail)
        self.save_warning.setVisible(health.saving_failed)
        if health.saving_failed:
            self.save_warning.setText(
                tr(
                    (
                        "Automatic recording is observing activity but cannot save "
                        "it. Observations are held until saved and saving is "
                        "retried. Error: {p0}"
                    ),
                    p0=health.detail,
                )
            )

    def _fill_overview(self, st: ActivityStats) -> None:
        self.cards["total"].set(
            _dur(st.total_ms), tr("Screen locked: {p0} (separate)", p0=_dur(st.locked_ms))
        )
        self.cards["active"].set(_dur(st.active_ms))
        self.cards["idle"].set(_dur(st.idle_ms))
        self.cards["switches"].set(tr("{p0} times", p0=st.switches))
        self.cards["sessions"].set(
            tr("{p0} sessions", p0=len(st.sessions)),
            tr("Average {p0}", p0=_dur(st.mean_session_ms))
            if st.sessions
            else tr("No sessions detected"),
        )
        hint = tr(WORK_HINT)
        if st.camera_covered_ms:
            hint = tr(
                "Excluding camera-estimated time away: {p0} (camera coverage: {p1})",
                p0=_dur(st.attended_work_ms),
                p1=_dur(st.camera_covered_ms),
            )
        if st.manual_overlap_ms:
            hint += tr(" · Overlap with focus sessions: {p0}", p0=_dur(st.manual_overlap_ms))
        self.cards["work"].set(_dur(st.work_ms), hint)

        total = sum(st.by_category.values()) or 1
        bars, t = [], 0
        for category in Category:
            ms = st.by_category.get(category, 0)
            if ms:
                bars.append(
                    Bar(
                        t,
                        t + ms,
                        CATEGORY_COLORS[category],
                        category,
                        f"{CATEGORY_LABELS[category]} {_dur(ms)} ({ms / total:.0%})",
                    )
                )
                t += ms
        self.category_bar.set_bars(bars, 0, max(total, 1))
        self.category_legend.setText(
            " · ".join(
                f"{CATEGORY_LABELS[c]} {_dur(ms)}" for c, ms in st.by_category.most_common() if ms
            )
            or tr("No records for this day.")
        )

        def shares(counter) -> list[list[str]]:
            active = st.active_ms or 1
            return [[name, _dur(ms), f"{ms / active:.0%}"] for name, ms in counter.most_common(15)]

        _fill(self.top_apps, shares(st.by_app))
        _fill(
            self.top_sites,
            shares(st.by_site) or [[tr("Connect the browser extension to see sites"), "", ""]],
        )

    def _fill_timeline(self, day_start: int, day_end: int) -> None:
        items = self._labeled
        if items:
            first = min(i.span.start_ms for i in items)
            last = max(i.span.end_ms for i in items)
            hour = 3_600_000
            start = max(day_start, day_start + (first - day_start) // hour * hour)
            end = min(day_end, day_start + -(-(last - day_start) // hour) * hour)
        else:
            start, end = day_start + 8 * 3_600_000, day_start + 20 * 3_600_000
        bars = [
            Bar(
                i.span.start_ms,
                i.span.end_ms,
                CATEGORY_COLORS[i.label.category],
                i,
                self._tooltip(i),
            )
            for i in items
        ]
        step = 3_600_000 if end - start <= 12 * 3_600_000 else 2 * 3_600_000
        # No strftime with Korean text: it fails under a non-Korean Windows locale.
        ticks = [
            (t, tr("{p0:02d}:00", p0=datetime.fromtimestamp(t / 1000).hour))
            for t in range(start, end + 1, step)
        ]
        self.timeline.set_bars(bars, start, end, ticks=ticks)

    def _tooltip(self, item: LabeledSpan) -> str:
        span, label = item.span, item.label
        lines = [
            f"{_hm(span.start_ms)}–{_hm(span.end_ms)} ({_dur(span.duration_ms)})",
            KIND_TEXT.get(span.kind) or span_label(span),
            tr(
                "{p0} · Confidence {p1:.0%}",
                p0=CATEGORY_LABELS[label.category],
                p1=label.confidence,
            ),
            tr(
                "Evidence: {p0} ({p1})",
                p0=CLASS_REASON_TEXT[label.reason],
                p1=SOURCE_TEXT[label.source],
            ),
        ]
        camera = _camera_text(item)
        if camera:
            lines.append(tr("Camera: {p0}", p0=camera))
        return "\n".join(lines)

    def _fill_spans(self) -> None:
        hide = self.hide_short.isChecked()
        self._rows = [i for i in self._labeled if not hide or i.span.duration_ms >= 10_000]
        rows = []
        for item in self._rows:
            span, label = item.span, item.label
            name = KIND_TEXT.get(span.kind) or (
                span.display_name
                or span.exe_name
                or (tr("Excluded") if span.excluded else tr("Unknown"))
            )
            rows.append(
                [
                    _hm(span.start_ms),
                    _hm(span.end_ms),
                    _dur(span.duration_ms),
                    name,
                    span.domain or "",
                    CATEGORY_LABELS[label.category],
                    f"{label.confidence:.0%}",
                    f"{CLASS_REASON_TEXT[label.reason]} · {SOURCE_TEXT[label.source]}",
                    _camera_text(item),
                ]
            )
        _fill(self.spans, rows)
        self._set_correction_enabled(False)

    def _fill_sessions(self, st: ActivityStats) -> None:
        rows = []
        for s in st.sessions:
            apps = ", ".join(name for name, _ in sorted(s.apps.items(), key=lambda kv: -kv[1])[:3])
            returns = (
                tr("{p0} times · Average return {p1}", p0=s.detours, p1=_dur(s.mean_return_ms))
                if s.return_ms
                else tr("{p0} times", p0=s.detours)
            )
            rows.append(
                [
                    f"{_hm(s.start_ms)[:5]}–{_hm(s.end_ms)[:5]}",
                    CATEGORY_LABELS[s.category],
                    _dur(s.active_ms),
                    _dur(s.interrupted_ms),
                    tr("{p0} times", p0=s.switches),
                    returns,
                    apps,
                    f"#{s.manual_session_id}" if s.manual_session_id else "",
                ]
            )
        _fill(
            self.sessions,
            rows or [[tr("No automatic sessions detected"), "", "", "", "", "", "", ""]],
        )

    def _fill_statistics(self, first: date, days: int, st: ActivityStats) -> None:
        columns = []
        for i in range(days):
            d = first + timedelta(days=i)
            label = f"{d.month}/{d.day}" + (f"({weekday_name(d.weekday())})" if days <= 7 else "")
            values = {c: ms / 1000 for c, ms in st.daily.get(d, {}).items()}
            columns.append((label, values))
        self.daily.label_every = 1 if days <= 7 else 5
        self.daily.set_columns(columns)
        self.hourly.set_columns(
            [(tr("{p0}:00", p0=h), {"active": ms / 1000}) for h, ms in enumerate(st.hourly_ms)]
        )

        def top(counter) -> str:
            return ", ".join(f"{name} {_dur(ms)}" for name, ms in counter.most_common(5)) or tr(
                "None"
            )

        transitions = ", ".join(
            tr("{p0} → {p1}: {p2} times", p0=a, p1=b, p2=n)
            for (a, b), n in st.transitions.most_common(5)
        ) or tr("None")
        active_days = sum(1 for counts in st.daily.values() if sum(counts.values()))
        self.range_summary.setText(
            tr(
                (
                    "<b>Period total</b>: PC use {p0}, input-based active {p1}, idle {p2} · Days "
                    "recorded: {p3} · Daily average input-based active time: {p4}<br><b>Top "
                    "programs</b>: {p5}<br><b>Top sites</b>: {p6}<br><b>Frequent switches</b>: "
                    "{p7}<br><b>Work continuity / returns</b>: {p8} automatic sessions, average "
                    "length {p9}, average return after a detour {p10}"
                ),
                p0=_dur(st.total_ms),
                p1=_dur(st.active_ms),
                p2=_dur(st.idle_ms),
                p3=active_days,
                p4=_dur(st.active_ms / max(1, active_days)),
                p5=top(st.by_app),
                p6=top(st.by_site),
                p7=transitions,
                p8=len(st.sessions),
                p9=_dur(st.mean_session_ms),
                p10=_dur(st.mean_return_ms),
            )
        )

    # corrections ------------------------------------------------------------------
    def _set_correction_enabled(self, on: bool) -> None:
        for w in (self.correct_to, self.always, self.apply_button, self.clear_button):
            w.setEnabled(on)

    def _selected(self) -> LabeledSpan | None:
        rows = self.spans.selectionModel().selectedRows()
        return self._rows[rows[0].row()] if rows and rows[0].row() < len(self._rows) else None

    def _span_selected(self) -> None:
        item = self._selected()
        active = bool(item and item.span.kind is SpanKind.ACTIVE)
        self._set_correction_enabled(active)
        if item:
            self.timeline.select(item)
            self.correct_to.setCurrentIndex(self.correct_to.findData(item.label.category))
            target = self.ctx.rule_target(item.span) if active else None
            self.always.setEnabled(target is not None)
            self.always.setText(
                tr("Always apply to {p0}", p0=target[1])
                if target
                else tr("Always apply to this app / site")
            )

    def _timeline_clicked(self, item: LabeledSpan) -> None:
        if item not in self._rows:
            self.hide_short.setChecked(False)
        for row, candidate in enumerate(self._rows):
            if candidate is item or candidate == item:
                self.spans.selectRow(row)
                break

    def _apply_correction(self) -> None:
        item = self._selected()
        if item is None or item.span.span_id is None:
            return
        category = Category(self.correct_to.currentData())
        self.ctx.correct_span(item.span, category, self.always.isChecked())
        self.refresh()
        self.dataChanged.emit()

    def _clear_correction(self) -> None:
        item = self._selected()
        if item is None or item.span.span_id is None:
            return
        self.ctx.clear_span_correction(item.span)
        self.refresh()
        self.dataChanged.emit()
