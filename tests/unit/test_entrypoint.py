"""The CLI entry point exposes headless commands that never open sensors."""

import pytest

from focuslab import __version__
from focuslab.__main__ import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_check_reports_environment_without_creating_data(capsys, isolated_data_dir):
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert f"FocusLab {__version__}" in out
    assert "Face model:" in out and "PySide6" in out
    assert not isolated_data_dir.exists()
