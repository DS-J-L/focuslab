"""Both interface languages across pages, dialogs, and a running session."""

import re
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QAbstractButton, QLabel, QMessageBox, QScrollArea

from focuslab.activity.stats import local_day_bounds
from focuslab.demo import seed_demo_sessions
from focuslab.domain.activity import ActivitySpan, SpanKind
from focuslab.domain.models import SessionConfig, SessionMode
from focuslab.i18n import get_language
from focuslab.ui import consent
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import ACTIVITY, REPORT, SETTINGS, MainWindow
from focuslab.ui.onboarding import OnboardingDialog

HANGUL = re.compile("[가-힣]")


@pytest.fixture
def readable_fonts(qapp):
    """Windows off-screen Qt needs explicit fonts for meaningful layout measurements."""
    previous = qapp.font()
    registered = []
    for name in ("segoeui.ttf", "segoeuib.ttf", "malgun.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            registered.append(QFontDatabase.addApplicationFont(str(path)))
    qapp.setFont(QFont("Segoe UI", 10))
    yield
    qapp.setFont(previous)
    for font_id in registered:
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


@pytest.mark.parametrize("language", ["en", "ko"])
def test_pages_reports_tray_and_session_use_selected_language(
    qtbot, monkeypatch, settle, readable_fonts, language
):
    monkeypatch.setenv("FOCUSLAB_LANGUAGE", language)
    ctx = AppContext(demo=True)
    seed_demo_sessions(ctx.db_path)
    start, _ = local_day_bounds(datetime.now().astimezone().date())
    with ctx.activity_repo() as repo:
        repo.insert_span(ActivitySpan(start, start + 600_000, SpanKind.ACTIVE, "code.exe"))
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.show()
    try:
        settle(window)
        expected = (
            ["Home", "Activity", "Sessions", "Reports", "Settings"]
            if language == "en"
            else ["홈", "활동", "세션", "리포트", "설정"]
        )
        assert [window.nav.item(i).text() for i in range(5)] == expected
        for index in (ACTIVITY, REPORT, SETTINGS):
            window.go(index)
            settle(window)
        activity_scroll = window.activity.findChild(QScrollArea)
        assert activity_scroll.horizontalScrollBar().maximum() == 0
        assert window.activity.range.currentData() == 7
        assert window.activity.range.currentText() == (
            "Last 7 days" if language == "en" else "최근 7일"
        )
        window.activity.range.setCurrentIndex(1)
        settle(window)
        assert window.activity.range.currentData() == 30
        assert window.activity.cards["total"]._value.text() == (
            "10m 0s" if language == "en" else "10분 0초"
        )
        assert window.tray.pause_action.text() == (
            "Pause session" if language == "en" else "세션 일시정지"
        )
        if language == "en":
            widgets = window.findChildren(QLabel) + window.findChildren(QAbstractButton)
            assert not [(w.objectName(), w.text()) for w in widgets if HANGUL.search(w.text())]
        ctx.service._auto_tick = False
        goal = "My goal: 연구 {p0}"
        window.start_session(SessionConfig(goal, SessionMode.CODING, 0, ("code.exe",), False))
        assert window.session.title.text() == goal
        assert ctx.service.repository.get_session(ctx.service.snapshot().session_id).goal == goal
        assert window.session.pause_button.text() == ("Pause" if language == "en" else "일시정지")
    finally:
        window.close_down()


def test_language_preference_survives_restart_without_interrupting_a_session(
    qtbot, monkeypatch, settle
):
    monkeypatch.delenv("FOCUSLAB_LANGUAGE")
    monkeypatch.setattr("focuslab.i18n.system_language", lambda: "ko")
    ctx = AppContext(demo=True)
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    try:
        settle(window)
        ctx.service._auto_tick = False
        window.start_session(SessionConfig("Keep this goal", SessionMode.CODING, 0, (), False))
        sid = ctx.service.snapshot().session_id
        window.settings.language_combo.setCurrentIndex(
            window.settings.language_combo.findData("en")
        )
        assert get_language() == "ko"
        assert ctx.service.snapshot().session_id == sid
        assert ctx.language == "en"
        assert "다시 실행" in window.settings.language_notice.text()
    finally:
        window.close_down()
    restarted = AppContext(demo=True)
    try:
        assert get_language() == "en"
        assert restarted.language == "en"
        assert restarted.service.repository.get_session(sid).goal == "Keep this goal"
    finally:
        restarted.service.shutdown()


@pytest.mark.parametrize("language", ["en", "ko"])
def test_onboarding_and_all_consent_explanations_are_localized(qtbot, monkeypatch, language):
    monkeypatch.setenv("FOCUSLAB_LANGUAGE", language)
    ctx = AppContext(demo=True)
    captured = []

    def read_dialog(box):
        captured.append((box.windowTitle(), box.informativeText()))
        return 0

    monkeypatch.setattr(QMessageBox, "exec", read_dialog)
    onboarding = OnboardingDialog()
    qtbot.addWidget(onboarding)
    try:
        for ask in (
            consent.ask_activity_consent,
            consent.ask_camera_consent,
            consent.ask_browser_consent,
            consent.ask_recording_consent,
        ):
            assert not ask(onboarding)
        assert len(captured) == 4
        for title, body in captured:
            assert bool(HANGUL.search(title)) is (language == "ko")
            assert bool(HANGUL.search(body)) is (language == "ko")
        assert all(
            bool(HANGUL.search(label.text())) is (language == "ko")
            for label in onboarding.findChildren(QLabel)
            if label.text()
        )
    finally:
        onboarding.reject()
        ctx.service.shutdown()
