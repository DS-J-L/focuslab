"""Work modes added in Settings reach New session and the session record; the first-run guide
can be stepped through, skipped, and reopened from Settings."""

import re

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox

from focuslab.config import DEFAULT_ALLOWED_APPS
from focuslab.domain.models import SessionMode
from focuslab.i18n import set_language
from focuslab.services.session_service import Lifecycle
from focuslab.ui.context import AppContext
from focuslab.ui.guide import GuideDialog, guide_steps
from focuslab.ui.main_window import HOME, SETTINGS, MainWindow
from focuslab.ui.work_mode_dialog import WorkModeDialog
from focuslab.work_modes import BUILT_IN, new_mode

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
    assert index == len(BUILT_IN) + 1  # after the built-ins and a separator
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


def test_guide_steps_forward_and_back_and_can_be_skipped(qtbot):
    guide = GuideDialog()
    qtbot.addWidget(guide)
    count = len(guide_steps())
    assert guide.counter.text() == f"{count}단계 중 1단계"
    assert not guide.back.isEnabled() and guide.skip.isVisibleTo(guide)
    assert guide.next.text() == "다음"
    for _ in range(count - 1):
        guide.next.click()
    assert guide.last and guide.next.text() == "시작하기"
    assert not guide.skip.isVisibleTo(guide)
    guide.back.click()
    assert guide.step == count - 2 and guide.skip.isVisibleTo(guide)
    guide.skip.click()
    assert guide.result() == GuideDialog.DialogCode.Rejected

    finished = GuideDialog()
    qtbot.addWidget(finished)
    finished.show_step(count - 1)
    finished.next.click()
    assert finished.result() == GuideDialog.DialogCode.Accepted


@pytest.mark.parametrize("language", ["en", "ko"])
def test_guide_is_localized(qtbot, language):
    set_language(language)
    guide = GuideDialog()
    qtbot.addWidget(guide)
    for step in range(len(guide_steps())):
        guide.show_step(step)
        texts = [label.text() for label in guide.findChildren(QLabel) if label.text()]
        texts += [guide.next.text(), guide.back.text(), guide.skip.text(), guide.windowTitle()]
        assert all(bool(HANGUL.search(t)) is (language == "ko") for t in texts), texts


def test_guide_is_offered_once_and_reopens_from_settings(window, monkeypatch):
    ctx = window.ctx
    assert not ctx.needs_guide  # never in demo mode
    shown = []
    monkeypatch.setattr(GuideDialog, "exec", lambda self: shown.append(self) or 0)
    assert not ctx.flag("guide.done")
    window.settings.show_guide()  # skipped (rejected) still counts as seen
    assert len(shown) == 1 and ctx.flag("guide.done")
    ctx.demo = False
    assert not ctx.needs_guide
    ctx.set_flag("guide.done", False)
    assert ctx.needs_guide
