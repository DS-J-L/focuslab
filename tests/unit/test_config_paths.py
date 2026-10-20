"""Bundled resources resolve inside a PyInstaller build, not next to its _internal folder."""

import subprocess
import sys

FROZEN_PROBE = """
import sys
sys.frozen, sys._MEIPASS = True, sys.argv[1]
from focuslab import config, model_fetch
print(config.face_model_path())
print(config.EXTENSION_DIR)
print(model_fetch.target_dir())
"""


def test_frozen_build_finds_bundled_model(tmp_path, monkeypatch, isolated_data_dir):
    bundle = tmp_path / "_internal"
    models = bundle / "assets" / "models"
    models.mkdir(parents=True)
    (models / "face_landmarker.task").write_bytes(b"model")
    monkeypatch.delenv("FOCUSLAB_MODEL_DIR", raising=False)
    out = subprocess.run(
        [sys.executable, "-c", FROZEN_PROBE, str(bundle)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert out == [
        str(models / "face_landmarker.task"),
        str(bundle / "browser_extension"),
        # Downloads go to the user's data folder, never into the install folder.
        str(isolated_data_dir / "models"),
    ]
