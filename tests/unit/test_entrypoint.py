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


def test_packaged_exe_downloads_models_into_data_folder(monkeypatch, isolated_data_dir):
    from focuslab import model_fetch

    monkeypatch.setattr(model_fetch, "FROZEN", True)  # never write into the exe bundle
    assert model_fetch.target_dir() == isolated_data_dir / "models"


@pytest.mark.parametrize(
    "status,code", [("NOT_INSTALLED", 0), ("RUNTIME_MISSING", 1)]
)
def test_relevance_selftest_without_a_usable_model(monkeypatch, capsys, status, code):
    from focuslab.relevance import model_manager

    monkeypatch.setattr(model_manager, "status", lambda: model_manager.ModelStatus(status))
    assert main(["--relevance-selftest"]) == code
    assert status in capsys.readouterr().out


def test_relevance_selftest_reports_a_model_that_cannot_load(monkeypatch, capsys, tmp_path):
    from focuslab.relevance import model_manager

    def broken(folder):
        raise ValueError("checksum mismatch for m.onnx")

    monkeypatch.setattr(model_manager, "status", lambda: model_manager.ModelStatus.READY)
    monkeypatch.setattr(model_manager, "installed_dir", lambda: tmp_path)
    monkeypatch.setattr(model_manager, "load", broken)
    assert main(["--relevance-selftest"]) == 1
    assert "checksum mismatch" in capsys.readouterr().out
