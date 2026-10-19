import os

import pytest

# Qt widgets render off-screen in tests so CI and local runs never flash windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeClock:
    def __init__(self, ms: int = 1_000_000) -> None:
        self.ms = ms

    def monotonic_ms(self) -> int:
        return self.ms

    def advance(self, seconds: float) -> None:
        self.ms += int(seconds * 1000)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Never touch the real %LOCALAPPDATA%\\FocusLab during tests."""
    monkeypatch.setenv("FOCUSLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"
