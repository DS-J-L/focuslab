"""One-click update window: one progress bar over download and unpack, cancel, errors."""

import threading

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox

from focuslab import updater
from focuslab.ui import update_dialog
from focuslab.ui.context import AppContext
from focuslab.ui.main_window import SETTINGS, MainWindow
from focuslab.ui.settings_page import SettingsPage
from focuslab.ui.update_dialog import DOWNLOAD, UNPACK, UpdateDialog

RELEASE = updater.Release("99.0.0", "https://example.invalid/r", "zip-url", "sha-url")


@pytest.fixture
def page(qtbot, monkeypatch):
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(update_dialog, "READY_PAUSE_MS", 0)
    ctx = AppContext(demo=True)
    settings = SettingsPage(ctx)
    qtbot.addWidget(settings)
    settings._release = RELEASE
    yield settings
    ctx.service.shutdown()


def fake_stage(tmp_path):
    def stage(package, target, progress=None, cancelled=None):
        progress(5, 10)
        progress(10, 10)
        staged = tmp_path / ".FocusLab-update"
        staged.mkdir()
        return staged

    return stage


def test_one_click_downloads_unpacks_and_hands_over_for_restart(page, qtbot, monkeypatch, tmp_path):
    def download(release, dest, progress=None, cancelled=None):
        dest.mkdir(parents=True, exist_ok=True)
        progress(50 * 1024 * 1024, 100 * 1024 * 1024)
        progress(100 * 1024 * 1024, 100 * 1024 * 1024)
        package = dest / "pkg.zip"
        package.write_bytes(b"zip")
        return package

    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "stage", fake_stage(tmp_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("no extra prompt"))
    restarts = []
    page.restartForUpdate.connect(restarts.append)

    page.update_button.click()
    dialog = page._update_dialog
    assert dialog is not None and dialog.isVisible()
    assert "99.0.0" in dialog.findChild(QLabel, "PageTitle").text()
    qtbot.waitUntil(lambda: bool(restarts), timeout=5000)
    assert restarts == [tmp_path / ".FocusLab-update"]
    assert dialog.bar.value() == 100 and dialog.percent.text() == "100%"
    assert not (page.ctx.data_dir / "updates" / "pkg.zip").exists()  # the zip is removed
    assert page.update_state.text() == "업데이트 준비 완료. FocusLab을 다시 시작해 마무리합니다."
    qtbot.waitUntil(lambda: page._update_dialog is None)


def test_progress_is_one_bar_across_download_and_unpack(qtbot):
    dialog = UpdateDialog(RELEASE)
    qtbot.addWidget(dialog)
    dialog._progress(DOWNLOAD, 50, 100)
    assert dialog.bar.value() == 40 and dialog.percent.text() == "40%"
    assert "/ 0.0 MB" in dialog.detail.text() and "MB/s" in dialog.detail.text()
    assert dialog.step.text() == "받는 중…"
    dialog._progress(UNPACK, 50, 100)
    assert dialog.bar.value() == 90
    assert dialog.step.text() == "업데이트 준비 중…"
    dialog._progress(DOWNLOAD, 3 * 1024 * 1024, 0)  # no Content-Length: a moving bar
    assert (dialog.bar.minimum(), dialog.bar.maximum()) == (0, 0)
    assert dialog.detail.text().startswith("3.0 MB")


def test_cancel_stops_the_download_and_installs_nothing(page, qtbot, monkeypatch):
    started = threading.Event()

    def download(release, dest, progress=None, cancelled=None):
        started.set()
        while not cancelled():
            threading.Event().wait(0.01)
        raise updater.UpdateCancelled

    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "stage", lambda *a, **k: pytest.fail("must not unpack"))
    restarts = []
    page.restartForUpdate.connect(restarts.append)
    page.start_update()
    dialog = page._update_dialog
    assert started.wait(5)
    dialog.cancel_button.click()
    assert dialog.step.text() == "취소하는 중…"
    qtbot.waitUntil(lambda: page._update_dialog is None, timeout=5000)
    assert not dialog.isVisible() and not restarts
    assert page.update_state.text() == "업데이트를 취소했습니다."
    assert page.update_button.isEnabled()


def test_close_box_while_running_cancels_instead_of_hiding(page, qtbot, monkeypatch):
    def download(release, dest, progress=None, cancelled=None):
        while not cancelled():
            threading.Event().wait(0.01)
        raise updater.UpdateCancelled

    monkeypatch.setattr(updater, "download", download)
    page.start_update()
    dialog = page._update_dialog
    dialog.close()
    assert dialog.isVisible()  # stays open until the worker has cleaned up
    qtbot.waitUntil(lambda: not dialog.isVisible(), timeout=5000)


def test_a_failed_update_stays_on_screen_with_the_reason(page, qtbot, monkeypatch):
    def download(release, dest, progress=None, cancelled=None):
        raise ValueError("checksum mismatch: abc")

    monkeypatch.setattr(updater, "download", download)
    page.start_update()
    dialog = page._update_dialog
    qtbot.waitUntil(lambda: dialog.cancel_button.text() == "닫기", timeout=5000)
    assert "checksum mismatch" in dialog.step.text()
    assert dialog.isVisible()
    assert "checksum mismatch" in page.update_state.text()
    dialog.cancel_button.click()
    assert not dialog.isVisible() and page._update_dialog is None


def test_sidebar_update_button_starts_the_update_in_one_click(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(update_dialog, "READY_PAUSE_MS", 0)
    monkeypatch.setattr(updater, "latest_release", lambda: RELEASE)
    swaps = []
    monkeypatch.setattr("focuslab.ui.main_window.updater.launch_swap", lambda *a: swaps.append(a))
    monkeypatch.setattr("focuslab.ui.main_window.QApplication.quit", lambda: None)

    def download(release, dest, progress=None, cancelled=None):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "pkg.zip").write_bytes(b"zip")
        return dest / "pkg.zip"

    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "stage", fake_stage(tmp_path))
    win = MainWindow(AppContext(demo=True))
    qtbot.addWidget(win)
    win.show()
    win.settings.check_updates()
    qtbot.waitUntil(win.update_button.isVisible, timeout=5000)
    win.update_button.click()
    assert win.stack.currentIndex() == SETTINGS
    qtbot.waitUntil(lambda: bool(swaps), timeout=5000)
    assert swaps[0][0] == tmp_path / ".FocusLab-update"
    assert not win._timer.isActive()  # shut down before the swap helper takes over
