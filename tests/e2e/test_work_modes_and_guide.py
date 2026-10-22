"""Work modes added in Settings reach New session and the session record; the first-run guide
points at each place it explains, can be skipped, and reopens from Settings."""

import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from focuslab.config import DEFAULT_ALLOWED_APPS
from focuslab.domain.models import SessionMode
from focuslab.i18n import set_language
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.guide import guide_steps
from focuslab.ui.main_window import ACTIVITY, HOME, SETTINGS, MainWindow
from focuslab.ui.work_mode_dialog import WorkModeDialog
from focuslab.work_modes import BUILT_IN, PRESETS, new_mode

HANGUL = re.compile("[가-힣]")


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "_ask_self_report", lambda self, sid: None)
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    yield win
    win.close_down()


def open_bubble(window, qtbot):
    window.home.fab.click()
    bubble = window.home.popover
    qtbot.waitUntil(lambda: bubble.graphicsEffect() is None)
    return bubble


def test_a_mode_added_in_settings_starts_a_session_under_its_own_name(window, qtbot):
    design = new_mode("디자인", SessionMode.READING_WRITING)
    window.ctx.save_work_mode(design)
    bubble = open_bubble(window, qtbot)
    combo = bubble.form.mode
    index = combo.findData(design.key)
    assert index == len(BUILT_IN) + len(PRESETS) + 2  # after built-ins, presets, separators
    assert combo.itemText(index) == "디자인"
    combo.setCurrentIndex(index)
    assert bubble.form.mode_hint.text().startswith("독서·필기처럼 판정합니다.")
    expected = sorted(set(DEFAULT_ALLOWED_APPS[SessionMode.READING_WRITING]))
    assert bubble.form._current_apps() == tuple(expected)

    bubble.form.show_apps(True)
    bubble.form.manual_app.setText("figma.exe")
    bubble.form._add_app_manual()
    assert "figma.exe" in window.ctx.allowed_apps(design)
    assert "figma.exe" not in window.ctx.allowed_apps(BUILT_IN[2])  # Reading / writing

    bubble.form.goal.setText("로고 시안")
    bubble.form.camera.setChecked(False)
    bubble.start_button.click()
    snap = window.ctx.service.snapshot()
    assert snap.lifecycle is Lifecycle.RUNNING
    assert snap.config.mode is SessionMode.READING_WRITING and snap.config.mode_name == "디자인"
    assert window.ctx.setting("last.mode") == design.key
    assert window.session.subtitle.text().startswith("디자인 모드")
    sid = snap.session_id
    window.finish_session()
    assert window.ctx.service.repository.get_session(sid).mode_name == "디자인"
    window.home.refresh()
    assert "(디자인)" in window.home.recent.item(0).text()

    # Deleting the mode keeps the past session's name and falls back to the first mode.
    window.ctx.delete_work_mode(design)
    assert window.ctx.setting(f"allowed_apps.{design.key}") is None
    assert window.ctx.service.repository.get_session(sid).mode_name == "디자인"
    window.go(HOME)
    bubble = open_bubble(window, qtbot)
    assert bubble.form.mode.findData(design.key) == -1
    assert bubble.form.current_mode() == BUILT_IN[0]


def test_a_preset_starts_a_session_under_its_name_with_its_apps(window, qtbot):
    bubble = open_bubble(window, qtbot)
    combo = bubble.form.mode
    meeting = PRESETS[0]
    index = combo.findData(meeting.key)
    assert index == len(BUILT_IN) + 1  # after the built-ins and a separator
    combo.setCurrentIndex(index)
    assert combo.itemText(index) == "회의·화상 통화"
    assert bubble.form.mode_hint.text().endswith("강의처럼 판정합니다.")
    assert "zoom.exe" in bubble.form._current_apps()
    bubble.form.camera.setChecked(False)
    bubble.start_button.click()
    snap = window.ctx.service.snapshot()
    assert snap.config.mode is SessionMode.LECTURE and snap.config.mode_name == "회의·화상 통화"
    window.finish_session()


def test_settings_lists_adds_edits_and_deletes_modes(window, monkeypatch):
    window.go(SETTINGS)
    settings = window.settings
    assert settings.modes.item(0).text() == "아직 추가한 모드가 없습니다."
    assert not settings.edit_mode.isEnabled() and not settings.delete_mode.isEnabled()

    def fill_and_save(name, base):
        def run(dialog):
            dialog.name.setText(name)
            dialog.base.setCurrentIndex(dialog.base.findData(base.value))
            return WorkModeDialog.DialogCode.Accepted

        return run

    monkeypatch.setattr(WorkModeDialog, "exec", fill_and_save("어학", SessionMode.LECTURE))
    settings._add_mode()
    [mode] = window.ctx.custom_modes()
    assert (mode.name, mode.base) == ("어학", SessionMode.LECTURE)
    assert settings.modes.item(0).text() == "어학 · 강의처럼 판정"

    settings.modes.setCurrentRow(0)
    assert settings.edit_mode.isEnabled()
    monkeypatch.setattr(WorkModeDialog, "exec", fill_and_save("어학 공부", SessionMode.CODING))
    settings._edit_mode()
    assert window.ctx.custom_modes() == [type(mode)(mode.key, SessionMode.CODING, "어학 공부")]

    settings.modes.setCurrentRow(0)
    settings._delete_mode()
    assert window.ctx.custom_modes() == []


def test_mode_dialog_refuses_empty_and_duplicate_names(qtbot):
    dialog = WorkModeDialog({"코딩", "디자인"})
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "작업 모드 추가" and not dialog.save.isEnabled()
    dialog.name.setText("  디자인 ")
    assert not dialog.save.isEnabled() and dialog.problem.isVisibleTo(dialog)
    dialog.name.setText("Coding")
    assert dialog.save.isEnabled()
    dialog.name.setText("시험 준비")
    dialog.base.setCurrentIndex(dialog.base.findData(SessionMode.READING_WRITING.value))
    assert dialog.save.isEnabled() and not dialog.problem.isVisibleTo(dialog)
    assert "종이" in dialog.hint.text()
    mode = dialog.result_mode()
    assert (mode.name, mode.base) == ("시험 준비", SessionMode.READING_WRITING)

    edit = WorkModeDialog({"코딩"}, mode)
    qtbot.addWidget(edit)
    assert edit.windowTitle() == "작업 모드 편집" and edit.save.isEnabled()
    assert edit.current_base() is SessionMode.READING_WRITING
    assert edit.result_mode().key == mode.key


TARGET_PAGES = {
    None: None,
    "home": HOME,
    "activity": None,
    "new_session": HOME,
    "work_modes": SETTINGS,
    "recording": SETTINGS,
    "reports": None,
    "guide": SETTINGS,
}


def test_guide_points_at_each_place_and_ends_where_it_began(window, qtbot):
    window.go(ACTIVITY)
    window.show_guide()
    tour = window.tour
    steps = guide_steps()
    assert tour.isVisible() and tour.geometry() == window.centralWidget().rect()
    assert tour.counter.text() == f"{len(steps)}단계 중 1단계"
    assert not tour.back.isEnabled() and tour.skip.isVisibleTo(tour)
    assert tour.next.text() == "다음"
    assert tour._hole.isEmpty()  # the welcome step points at nothing: a centered bubble
    assert set(TARGET_PAGES) == {step.target for step in steps}

    for number, step in enumerate(steps[1:], start=2):
        tour.next.click()
        QApplication.processEvents()  # the step is placed again once the page has switched
        assert tour.counter.text() == f"{len(steps)}단계 중 {number}단계"
        if TARGET_PAGES[step.target] is not None:
            assert window.stack.currentIndex() == TARGET_PAGES[step.target]
        assert not tour._hole.isEmpty(), step.target
        assert tour.rect().contains(tour.bubble.geometry())
        assert not tour.bubble.geometry().intersects(tour._hole), step.target

    def center_in_hole(widget):
        return tour._hole.contains(tour.mapFromGlobal(widget.mapToGlobal(widget.rect().center())))

    assert center_in_hole(window.settings.guide_button)
    assert tour.last and tour.next.text() == "시작하기" and not tour.skip.isVisibleTo(tour)
    tour.back.click()
    assert tour.step == len(steps) - 2 and tour.skip.isVisibleTo(tour)
    tour.show_step(5)
    QApplication.processEvents()
    assert center_in_hole(window.settings.recording_button)
    tour.show_step(3)
    QApplication.processEvents()
    assert window.stack.currentIndex() == HOME and center_in_hole(window.home.fab)

    ended = []
    tour.finished.connect(ended.append)
    QTest.keyClick(tour, Qt.Key.Key_Escape)
    assert ended == [False] and window.tour is None and not tour.isVisible()
    assert window.stack.currentIndex() == ACTIVITY  # back where the tour began

    window.show_guide()
    window.tour.finished.connect(ended.append)
    window.tour.show_step(len(steps) - 1)
    window.tour.next.click()
    assert ended == [False, True] and window.tour is None


@pytest.mark.parametrize("language", ["en", "ko"])
def test_guide_is_localized(window, language):
    set_language(language)
    window.show_guide()
    tour = window.tour
    for step in range(len(guide_steps())):
        tour.show_step(step)
        texts = [label.text() for label in tour.findChildren(QLabel) if label.text()]
        texts += [tour.next.text(), tour.back.text(), tour.skip.text(), tour.accessibleName()]
        assert all(bool(HANGUL.search(t)) is (language == "ko") for t in texts), texts
    tour.close_tour(False)


def test_guide_is_offered_once_and_reopens_from_settings(window):
    ctx = window.ctx
    assert not ctx.needs_guide  # never in demo mode
    assert not ctx.flag("guide.done")
    window.go(SETTINGS)
    window.settings.guide_button.click()
    tour = window.tour
    assert tour is not None and tour.isVisible() and ctx.flag("guide.done")
    window.settings.guide_button.click()  # already open: no second tour
    assert window.tour is tour
    tour.skip.click()  # skipped still counts as seen
    assert window.tour is None and ctx.flag("guide.done")
    ctx.demo = False
    assert not ctx.needs_guide
    ctx.set_flag("guide.done", False)
    assert ctx.needs_guide


def test_settings_shows_the_build_and_when_this_pc_first_ran_it(window, monkeypatch):
    from datetime import datetime

    from focuslab import build_info

    labels = [w.text() for w in window.settings.findChildren(QLabel)]
    build = build_info.current()
    assert any(t.startswith(build.commit + " · 커밋") for t in labels)
    since = window.ctx.setting("app.build_since")
    assert window.ctx.setting("app.build") == build.key
    assert any(t.startswith(f"{datetime.fromisoformat(since):%Y-%m-%d %H:%M}") for t in labels)
    window.settings._note_build()  # the same build again keeps its first start
    assert window.ctx.setting("app.build_since") == since
