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
from focuslab.ui.context import AppContext
from focuslab.ui.recording_status import WARNING_STYLE, RecordingHealth
from focuslab.ui.report_worker import ActivityReporter
from focuslab.ui.theme import CATEGORY_COLORS, CATEGORY_LABELS
from focuslab.ui.widgets import Bar, BarTimeline, Legend, StackedBars, StatCard

KIND_TEXT = {SpanKind.IDLE: "유휴(입력 없음)", SpanKind.LOCKED: "화면 잠금"}
SOURCE_TEXT = {
    ClassSource.RULE: "기본 규칙",
    ClassSource.USER_RULE: "내 규칙",
    ClassSource.USER: "직접 정정",
    ClassSource.SYSTEM: "관측 상태",
}
RANGES = {"최근 7일": 7, "최근 30일": 30}
_WEEKDAYS = "월화수목금토일"
DAY, RANGE = "activity.day", "activity.range"  # ActivityReporter keys
WORK_HINT = "개발·공부·문서·조사·업무 도구로 분류된 시간의 합계"
METRICS_NOTE = (
    "이 화면은 자동 기록입니다. '입력 기준 활성 시간'은 키보드·마우스 입력이 있던 시간이라, 입력"
    " 없이 강의를 보거나 글을 읽은 시간은 유휴로 잡힐 수 있습니다. '작업 카테고리 시간'은 앱·사이트"
    " 분류(개발·공부·문서·조사·업무 도구)의 합계입니다. 집중 세션 리포트의 '작업 관련 추정 시간'은"
    " 세션의 목표·허용 앱과 카메라 관찰로 판정하므로 같은 시간대라도 값이 다를 수 있습니다."
    " 예를 들어 허용 앱에 없는 문서 편집기는 여기서는 작업이지만"
    " 세션에서는 이탈 의심일 수 있습니다."
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
        return "집중 세션(카메라 없음)"
    parts = [f"{label} {seconds}초" for label, seconds in (
        ("자리 비움", ov.away_s), ("얼굴 안 보임", ov.face_absent_s),
        ("화면 외 방향", ov.head_away_s), ("아래쪽", ov.head_down_s),
    ) if seconds]
    return " · ".join(parts) or "화면 방향 관찰"


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
        head.addWidget(QLabel("활동", objectName="PageTitle"))
        head.addStretch()
        self.loading = QLabel(objectName="Muted")
        head.addWidget(self.loading)
        self.status = QLabel(objectName="Muted")
        head.addWidget(self.status)
        prev, nxt, today = QPushButton("◀"), QPushButton("▶"), QPushButton("오늘")
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
            "total": StatCard("총 PC 사용", hint="활성 + 유휴 (잠금·절전 제외)"),
            "active": StatCard("입력 기준 활성 시간",
                               hint="키보드·마우스 입력이 있던 시간 (입력 없는 시청·읽기는 유휴)"),
            "idle": StatCard("유휴"),
            "switches": StatCard("작업 전환", hint="프로그램·사이트가 바뀐 횟수"),
            "sessions": StatCard("자동 세션", hint="타이머 없이 감지한 작업 구간"),
            "work": StatCard("작업 카테고리 시간", hint=WORK_HINT),
        }
        for i, card in enumerate(self.cards.values()):
            cards.addWidget(card, i // 3, i % 3)
        root.addLayout(cards)
        self.metrics_note = QLabel(METRICS_NOTE, objectName="Muted", wordWrap=True)
        root.addWidget(self.metrics_note)

        self.category_bar = BarTimeline(30)
        self.category_legend = QLabel(objectName="Muted", wordWrap=True)
        box = QGroupBox("카테고리별 시간")
        lay = QVBoxLayout(box)
        lay.addWidget(self.category_bar)
        lay.addWidget(self.category_legend)
        root.addWidget(box)

        box = QGroupBox("하루 타임라인")
        lay = QVBoxLayout(box)
        self.timeline = BarTimeline(56)
        self.timeline.itemClicked.connect(self._timeline_clicked)
        lay.addWidget(self.timeline)
        lay.addWidget(Legend([(CATEGORY_COLORS[c], CATEGORY_LABELS[c]) for c in Category]))
        root.addWidget(box)

        tops = QHBoxLayout()
        self.top_apps = _table(["프로그램", "시간", "비율"], 0)
        self.top_sites = _table(["사이트", "시간", "비율"], 0)
        for title, table in (("프로그램별 사용 시간", self.top_apps),
                             ("웹사이트별 사용 시간", self.top_sites)):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(table)
            table.setMinimumHeight(140)
            table.setMaximumHeight(260)
            tops.addWidget(box)
        root.addLayout(tops)

        root.addWidget(self._build_spans())

        box = QGroupBox("자동 세션 (수동 집중 세션과 겹치면 표시, 시간은 한 번만 집계)")
        lay = QVBoxLayout(box)
        self.sessions = _table(["시간", "작업 종류", "활성", "중단", "전환", "우회·복귀", "주요 앱",
                                "집중 세션"], 6)
        self.sessions.setMinimumHeight(120)
        self.sessions.setMaximumHeight(260)
        lay.addWidget(self.sessions)
        root.addWidget(box)

        root.addWidget(self._build_statistics())
        self.notice = QLabel(
            "기록은 관찰된 PC 사용의 추정입니다. 자리 비움은 얼굴이 보이지 않고 입력도 없을 때만"
            " 작업 시간에서 빼며, 화면을 보지 않았다는 이유만으로 딴짓으로 판단하지 않습니다.",
            objectName="Notice", wordWrap=True,
        )
        root.addWidget(self.notice)

    # sections ---------------------------------------------------------------------
    def _build_spans(self) -> QGroupBox:
        box = QGroupBox("활동 구간")
        lay = QVBoxLayout(box)
        top = QHBoxLayout()
        self.hide_short = QCheckBox("10초 미만 구간 숨기기")
        self.hide_short.setChecked(True)
        self.hide_short.toggled.connect(self._fill_spans)
        top.addWidget(self.hide_short)
        top.addStretch()
        lay.addLayout(top)
        self.spans = _table(["시작", "종료", "길이", "프로그램", "사이트", "분류", "신뢰도", "근거",
                             "웹캠 관찰"], 7)
        self.spans.setMinimumHeight(220)
        self.spans.setMaximumHeight(420)
        self.spans.itemSelectionChanged.connect(self._span_selected)
        lay.addWidget(self.spans)
        row = QHBoxLayout()
        row.addWidget(QLabel("선택한 구간을"))
        self.correct_to = QComboBox()
        for category in Category:
            self.correct_to.addItem(CATEGORY_LABELS[category], category)
        row.addWidget(self.correct_to)
        self.always = QCheckBox("이 앱·사이트에 항상 적용")
        row.addWidget(self.always)
        self.apply_button = QPushButton("정정")
        self.apply_button.clicked.connect(self._apply_correction)
        self.clear_button = QPushButton("정정 취소")
        self.clear_button.clicked.connect(self._clear_correction)
        row.addWidget(self.apply_button)
        row.addWidget(self.clear_button)
        row.addStretch()
        lay.addLayout(row)
        self._set_correction_enabled(False)
        return box

    def _build_statistics(self) -> QGroupBox:
        box = QGroupBox("통계")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.range = QComboBox()
        self.range.addItems(list(RANGES))
        self.range.currentIndexChanged.connect(self.refresh_statistics)
        row.addWidget(QLabel("기간"))
        row.addWidget(self.range)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("일별 카테고리 시간", objectName="CardTitle"))
        self.daily = StackedBars(list(Category), CATEGORY_COLORS)
        lay.addWidget(self.daily)
        lay.addWidget(QLabel("시간대별 입력 기준 활성 시간 (기간 합계)", objectName="CardTitle"))
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
        if (self.day == datetime.now().astimezone().date() and not self.spans.selectedItems()
                and not self.reporter.pending(DAY)):
            self.refresh(statistics=False)

    @property
    def loading_now(self) -> bool:
        return self.reporter.pending(DAY) or self.reporter.pending(RANGE)

    def refresh(self, statistics: bool = True) -> None:
        """Ask the worker for the day (and the long-range charts). The page keeps showing
        the previous result, and stays usable, until the new one arrives."""
        start, end = local_day_bounds(self.day)
        self.day_label.setText(f"{self.day:%Y-%m-%d} ({_WEEKDAYS[self.day.weekday()]})")
        self.set_recording_health(self.ctx.recording_health())
        self._set_correction_enabled(False)  # the rows may change under the selection
        self.reporter.request(DAY, start, end, (self.day, start, end))
        if statistics:
            self.refresh_statistics()
        self._show_loading()

    def refresh_statistics(self) -> None:
        days = RANGES[self.range.currentText()]
        first = self.day - timedelta(days=days - 1)
        start, _ = local_day_bounds(first)
        _, end = local_day_bounds(self.day)
        self.reporter.request(RANGE, start, end, (first, days))
        self._show_loading()

    def _show_loading(self, error: str | None = None) -> None:
        if error:
            self.loading.setText(f"불러오지 못했습니다: {error}")
        else:
            self.loading.setText("불러오는 중…" if self.loading_now else "")

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
        """Observing and saving, separately; a failing save stays visible until a save works."""
        self.status.setText(health.text)
        self.status.setStyleSheet(WARNING_STYLE if health.saving_failed else "")
        self.status.setToolTip(health.detail)
        self.save_warning.setVisible(health.saving_failed)
        if health.saving_failed:
            self.save_warning.setText(
                "자동 기록이 관찰은 하고 있지만 저장하지 못하고 있습니다. 관찰한 내용은"
                f" 저장될 때까지 보관하며 계속 다시 시도합니다. 오류: {health.detail}"
            )

    def _fill_overview(self, st: ActivityStats) -> None:
        self.cards["total"].set(_dur(st.total_ms), f"화면 잠금 {_dur(st.locked_ms)} 별도")
        self.cards["active"].set(_dur(st.active_ms))
        self.cards["idle"].set(_dur(st.idle_ms))
        self.cards["switches"].set(f"{st.switches}회")
        self.cards["sessions"].set(
            f"{len(st.sessions)}개",
            f"평균 {_dur(st.mean_session_ms)}" if st.sessions else "감지된 세션 없음",
        )
        hint = WORK_HINT
        if st.camera_covered_ms:
            hint = (f"카메라 기준 자리 비움 제외 {_dur(st.attended_work_ms)}"
                    f" (카메라 관찰 {_dur(st.camera_covered_ms)})")
        if st.manual_overlap_ms:
            hint += f" · 집중 세션과 겹침 {_dur(st.manual_overlap_ms)}"
        self.cards["work"].set(_dur(st.work_ms), hint)

        total = sum(st.by_category.values()) or 1
        bars, t = [], 0
        for category in Category:
            ms = st.by_category.get(category, 0)
            if ms:
                bars.append(Bar(t, t + ms, CATEGORY_COLORS[category], category,
                                f"{CATEGORY_LABELS[category]} {_dur(ms)} ({ms / total:.0%})"))
                t += ms
        self.category_bar.set_bars(bars, 0, max(total, 1))
        self.category_legend.setText(" · ".join(
            f"{CATEGORY_LABELS[c]} {_dur(ms)}" for c, ms in st.by_category.most_common() if ms
        ) or "이 날 기록이 없습니다.")

        def shares(counter) -> list[list[str]]:
            active = st.active_ms or 1
            return [[name, _dur(ms), f"{ms / active:.0%}"] for name, ms in counter.most_common(15)]

        _fill(self.top_apps, shares(st.by_app))
        _fill(self.top_sites, shares(st.by_site) or [["브라우저 확장 연결 시 표시됩니다", "", ""]])

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
        bars = [Bar(i.span.start_ms, i.span.end_ms, CATEGORY_COLORS[i.label.category], i,
                    self._tooltip(i)) for i in items]
        step = 3_600_000 if end - start <= 12 * 3_600_000 else 2 * 3_600_000
        # No strftime with Korean text: it fails under a non-Korean Windows locale.
        ticks = [(t, f"{datetime.fromtimestamp(t / 1000).hour:02d}시")
                 for t in range(start, end + 1, step)]
        self.timeline.set_bars(bars, start, end, ticks=ticks)

    def _tooltip(self, item: LabeledSpan) -> str:
        span, label = item.span, item.label
        lines = [f"{_hm(span.start_ms)}–{_hm(span.end_ms)} ({_dur(span.duration_ms)})",
                 KIND_TEXT.get(span.kind) or span_label(span),
                 f"{CATEGORY_LABELS[label.category]} · 신뢰도 {label.confidence:.0%}",
                 f"근거: {CLASS_REASON_TEXT[label.reason]} ({SOURCE_TEXT[label.source]})"]
        camera = _camera_text(item)
        if camera:
            lines.append(f"웹캠: {camera}")
        return "\n".join(lines)

    def _fill_spans(self) -> None:
        hide = self.hide_short.isChecked()
        self._rows = [i for i in self._labeled if not hide or i.span.duration_ms >= 10_000]
        rows = []
        for item in self._rows:
            span, label = item.span, item.label
            name = KIND_TEXT.get(span.kind) or (
                span.display_name or span.exe_name or ("제외됨" if span.excluded else "알 수 없음")
            )
            rows.append([
                _hm(span.start_ms), _hm(span.end_ms), _dur(span.duration_ms), name,
                span.domain or "", CATEGORY_LABELS[label.category], f"{label.confidence:.0%}",
                f"{CLASS_REASON_TEXT[label.reason]} · {SOURCE_TEXT[label.source]}",
                _camera_text(item),
            ])
        _fill(self.spans, rows)
        self._set_correction_enabled(False)

    def _fill_sessions(self, st: ActivityStats) -> None:
        rows = []
        for s in st.sessions:
            apps = ", ".join(name for name, _ in sorted(s.apps.items(), key=lambda kv: -kv[1])[:3])
            returns = (f"{s.detours}회 · 평균 복귀 {_dur(s.mean_return_ms)}" if s.return_ms
                       else f"{s.detours}회")
            rows.append([
                f"{_hm(s.start_ms)[:5]}–{_hm(s.end_ms)[:5]}", CATEGORY_LABELS[s.category],
                _dur(s.active_ms), _dur(s.interrupted_ms), f"{s.switches}회", returns, apps,
                f"#{s.manual_session_id}" if s.manual_session_id else "",
            ])
        _fill(self.sessions, rows or [["감지된 자동 세션이 없습니다", "", "", "", "", "", "", ""]])

    def _fill_statistics(self, first: date, days: int, st: ActivityStats) -> None:
        columns = []
        for i in range(days):
            d = first + timedelta(days=i)
            label = f"{d.month}/{d.day}" + (f"({_WEEKDAYS[d.weekday()]})" if days <= 7 else "")
            values = {c: ms / 1000 for c, ms in st.daily.get(d, {}).items()}
            columns.append((label, values))
        self.daily.label_every = 1 if days <= 7 else 5
        self.daily.set_columns(columns)
        self.hourly.set_columns([(f"{h}시", {"active": ms / 1000})
                                 for h, ms in enumerate(st.hourly_ms)])
        def top(counter) -> str:
            return ", ".join(f"{name} {_dur(ms)}" for name, ms in counter.most_common(5)) or "없음"

        transitions = ", ".join(
            f"{a} → {b} {n}회" for (a, b), n in st.transitions.most_common(5)) or "없음"
        active_days = sum(1 for counts in st.daily.values() if sum(counts.values()))
        self.range_summary.setText(
            f"<b>기간 합계</b>: PC 사용 {_dur(st.total_ms)},"
            f" 입력 기준 활성 {_dur(st.active_ms)}, 유휴 {_dur(st.idle_ms)}"
            f" · 기록이 있는 날 {active_days}일"
            f" · 하루 평균 입력 기준 활성 {_dur(st.active_ms / max(1, active_days))}<br>"
            f"<b>상위 프로그램</b>: {top(st.by_app)}<br>"
            f"<b>상위 사이트</b>: {top(st.by_site)}<br>"
            f"<b>자주 한 전환</b>: {transitions}<br>"
            f"<b>작업 유지·복귀</b>: 자동 세션 {len(st.sessions)}개, 평균 길이"
            f" {_dur(st.mean_session_ms)}, 우회 후 평균 복귀 {_dur(st.mean_return_ms)}"
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
                f"{target[1]}에 항상 적용" if target else "이 앱·사이트에 항상 적용"
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
