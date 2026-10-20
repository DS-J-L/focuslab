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


# The acceptance scenario of the activity engine, minute by minute:
# (minutes, foreground exe, site reported by the extension, user input?)
DAILY_SCENARIO = (
    (30, "code.exe", None, True),  # coding in VS Code
    (10, "chrome.exe", "github.com", True),  # checking GitHub in Chrome
    (10, "chrome.exe", "youtube.com", True),  # moving on to YouTube
    (10, "chrome.exe", "youtube.com", False),  # walks away from the PC
    (20, "code.exe", None, True),  # back to work
)


@pytest.fixture
def daily_scenario():
    """Run the real recorder (scripted probe, simulated clock) through ``DAILY_SCENARIO``
    starting at ``start_ms`` and return the database path."""
    from focuslab.activity.recorder import ActivityRecorder, RecorderConfig
    from focuslab.browser.protocol import BrowserState
    from focuslab.browser.store import BrowserStateStore
    from focuslab.domain.activity import ForegroundApp, ProbeSample
    from focuslab.storage.repository import Repository

    def run(db_path, start_ms: int):
        clock = FakeClock()
        base = clock.ms
        state = {"sample": None}

        class Probe:
            def sample(self):
                return state["sample"]

        def wall() -> int:
            return start_ms + clock.ms - base

        rec = ActivityRecorder(db_path, Probe(), clock=clock, wall=wall,
                               config=RecorderConfig(idle_threshold_s=300))
        rec.start(run_thread=False)
        repo = Repository(rec._repo.conn)
        for key in ("consent.recording", "consent.browser"):
            repo.set_setting(key, "1")
        rec.set_browser_tracking(True)
        host = BrowserStateStore(rec._repo.conn)
        seq = 0
        for minutes, exe, site, typing in DAILY_SCENARIO:
            for second in range(minutes * 60):
                # seconds since the last input; the first away second still has the input
                idle = 0 if typing else second
                if site:
                    seq += 1
                    host.apply(BrowserState("chrome", "w", seq, 0, True, site), wall())
                state["sample"] = ProbeSample(ForegroundApp(exe, exe.split(".")[0].title()),
                                              float(idle))
                rec.tick()
                clock.advance(1)
        rec.tick()
        rec.stop()
        return db_path

    return run
