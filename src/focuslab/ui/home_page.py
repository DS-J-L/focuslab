"""Home: today's summary, new session form (goal, mode, time, allowed apps, camera), recents."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focuslab.activity.windows_tracker import normalize, visible_window_apps
from focuslab.config import MODE_LABELS, NEUTRAL_APPS
from focuslab.domain.models import FocusState, SessionConfig, SessionMode
from focuslab.focus.metrics import apply_corrections, compute_metrics, format_duration, format_ratio
from focuslab.services.export_service import local_date
from focuslab.ui.context import AppContext
from focuslab.ui.widgets import StatCard

MODE_HINTS = {
    SessionMode.CODING: "IDE·터미널·문서. 화면 밖 시선만으로 이탈로 보지 않습니다.",
    SessionMode.LECTURE: "동영상 강의. 키보드·마우스 입력이 없어도 정상입니다.",
    SessionMode.READING_WRITING: (
        "종이책·필기. 아래쪽 시선을 작업으로 보고 자리 비움 판단을 늦춥니다."
    ),
    SessionMode.CUSTOM: "허용 앱을 직접 지정합니다.",
}


class HomePage(QWidget):
    startRequested = Signal(object)  # SessionConfig
    openReport = Signal(int)

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addWidget(QLabel("오늘", objectName="PageTitle"))

        cards = QGridLayout()
        self.card_sessions = StatCard("세션", "0", "오늘 시작한 세션")
        self.card_on = StatCard("작업 관련 추정 시간", "0초", "실제 집중의 증명은 아닙니다")
        self.card_off = StatCard("이탈 의심 시간", "0초", "정정 내용 반영")
        self.card_cov = StatCard("측정 커버리지", "측정 불가", "판단 불가를 제외한 비율")
        for i, card in enumerate((self.card_sessions, self.card_on, self.card_off, self.card_cov)):
            cards.addWidget(card, 0, i)
        root.addLayout(cards)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_form(), 3)
        recent_box = QGroupBox("최근 세션")
        recent_layout = QVBoxLayout(recent_box)
        self.recent = QListWidget()
        self.recent.setWordWrap(True)
        self.recent.itemClicked.connect(self._open_recent)
        recent_layout.addWidget(self.recent)
        body.addWidget(recent_box, 2)
        root.addLayout(body, 1)

    def _open_recent(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id is not None:
            self.openReport.emit(session_id)

    # form -------------------------------------------------------------------------
    def _build_form(self) -> QGroupBox:
        box = QGroupBox("새 세션")
        outer = QVBoxLayout(box)
        form = QFormLayout()
        outer.addLayout(form)
        outer.addStretch()
        form.setVerticalSpacing(10)
        self.goal = QLineEdit(self.ctx.setting("last.goal", "") or "")
        self.goal.setPlaceholderText("예: 알고리즘 문제 풀기")
        form.addRow("목표", self.goal)

        self.mode = QComboBox()
        for mode in SessionMode:
            self.mode.addItem(MODE_LABELS[mode], mode)
        last_mode = self.ctx.setting("last.mode", SessionMode.CODING.value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(SessionMode(last_mode))))
        self.mode_hint = QLabel(objectName="Muted")
        self.mode_hint.setWordWrap(True)
        form.addRow("작업 모드", self.mode)
        form.addRow("", self.mode_hint)

        self.minutes = QSpinBox()
        self.minutes.setRange(0, 240)
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(" 분")
        self.minutes.setSpecialValueText("제한 없음")
        self.minutes.setValue(int(self.ctx.setting("last.minutes", "25") or 25))
        form.addRow("목표 시간", self.minutes)

        self.apps = QListWidget()
        self.apps.setMaximumHeight(130)
        self.apps.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        app_buttons = QHBoxLayout()
        add = QPushButton("직접 추가…")
        add.clicked.connect(self._add_app_manual)
        self.add_open = QPushButton("열린 앱에서 추가…")
        self.add_open.clicked.connect(self._add_app_from_open)
        remove = QPushButton("선택 삭제")
        remove.clicked.connect(self._remove_apps)
        reset = QPushButton("기본값")
        reset.clicked.connect(self._reset_apps)
        for b in (add, self.add_open, remove, reset):
            app_buttons.addWidget(b)
        app_buttons.addStretch()
        apps_col = QVBoxLayout()
        apps_col.addWidget(self.apps)
        apps_col.addLayout(app_buttons)
        note = QLabel("프로세스 이름만 비교합니다. 브라우저는 사이트까지 구분하지 못합니다.",
                      objectName="Muted")
        note.setWordWrap(True)
        apps_col.addWidget(note)
        form.addRow("허용 앱", apps_col)

        self.camera = QCheckBox("웹캠으로 얼굴 존재·머리 방향 관찰 (선택)")
        self.camera.setChecked(self.ctx.flag("last.camera", False))
        form.addRow("카메라", self.camera)

        self.start_button = QPushButton("집중 시작", objectName="Primary")
        self.start_button.clicked.connect(self._start)
        form.addRow("", self.start_button)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()
        return box

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
        name, ok = QInputDialog.getText(self, "허용 앱 추가", "프로세스 이름 (예: code.exe)")
        if ok:
            self._add(name)

    def _add_app_from_open(self) -> None:
        menu = QMenu(self)
        names = [n for n in visible_window_apps() if normalize(n) not in NEUTRAL_APPS]
        for name in names:
            menu.addAction(name, lambda n=name: self._add(n))
        if not names:
            menu.addAction("열린 앱을 찾지 못했습니다").setEnabled(False)
        menu.exec(self.add_open.mapToGlobal(self.add_open.rect().bottomLeft()))

    def _remove_apps(self) -> None:
        for item in self.apps.selectedItems():
            self.apps.takeItem(self.apps.row(item))
        self._save_apps()

    def _reset_apps(self) -> None:
        self.ctx.set_allowed_apps(self.current_mode(), None)
        self._set_apps(self.ctx.allowed_apps(self.current_mode()))

    def _start(self) -> None:
        apps = self._current_apps()
        if not apps:
            answer = QMessageBox.question(
                self, "허용 앱 없음",
                "허용 앱이 비어 있으면 모든 앱이 '허용 목록에 없는 앱'으로 처리됩니다. 계속할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        goal = self.goal.text().strip() or "집중 세션"
        self.ctx.set_setting("last.goal", goal)
        self.ctx.set_setting("last.mode", self.current_mode().value)
        self.ctx.set_setting("last.minutes", str(self.minutes.value()))
        self.ctx.set_flag("last.camera", self.camera.isChecked())
        self.startRequested.emit(
            SessionConfig(goal, self.current_mode(), self.minutes.value(), apps,
                          self.camera.isChecked())
        )

    # summary ----------------------------------------------------------------------
    def refresh(self) -> None:
        today = datetime.now().astimezone().date()
        with self.ctx.service.lock:
            repo = self.ctx.service.repository
            sessions = repo.list_sessions(limit=50)
            todays = [s for s in sessions if local_date(s.started_at_utc) == today]
            samples = []
            for s in todays:
                samples += apply_corrections(repo.samples(s.id), repo.segments(s.id))
        metrics = compute_metrics(samples)
        self.card_sessions.set(str(len(todays)))
        self.card_on.set(format_duration(metrics.seconds[FocusState.ON_TASK]))
        self.card_off.set(format_duration(metrics.seconds[FocusState.POSSIBLY_OFF_TASK]))
        self.card_cov.set(format_ratio(metrics.coverage))

        self.recent.clear()
        for s in sessions[:12]:
            started = datetime.fromisoformat(s.started_at_utc).astimezone()
            status = {"FINISHED": "", "INTERRUPTED": " · 중단됨"}.get(s.status.value, " · 진행 중")
            item = QListWidgetItem(
                f"{started:%m/%d %H:%M}  {s.goal}  ({MODE_LABELS[s.mode]}){status}"
            )
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            self.recent.addItem(item)
        if not sessions:
            self.recent.addItem("아직 기록된 세션이 없습니다.")

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.start_button.setText("세션 진행 중" if running else "집중 시작")

