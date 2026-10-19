"""A recorder process killed mid-write leaves a consistent database and is detected next start."""

import subprocess
import sys
import textwrap
import time

from focuslab.activity.recorder import ActivityRecorder
from focuslab.domain.activity import ForegroundApp, ProbeSample, SystemEvent
from focuslab.storage.activity_repository import ActivityRepository
from focuslab.storage.sqlite_db import connect

CHILD = textwrap.dedent(
    """
    import sys, time
    from focuslab.activity.recorder import ActivityRecorder, RecorderConfig
    from focuslab.domain.activity import ForegroundApp, ProbeSample

    class Probe:
        def sample(self):
            return ProbeSample(ForegroundApp("code.exe"), 0.0)

    rec = ActivityRecorder(sys.argv[1], Probe(), config=RecorderConfig(poll_s=0.05, flush_s=0.2))
    rec.start()
    print("started", flush=True)
    time.sleep(60)
    """
)


class Probe:
    def sample(self) -> ProbeSample:
        return ProbeSample(ForegroundApp("code.exe"), 0.0)


def test_killed_recorder_keeps_flushed_spans_and_reports_recovery(tmp_path):
    db = tmp_path / "crash.db"
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(db)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout.readline().strip() == "started"
        time.sleep(1.5)  # several batches are written while the child keeps running
    finally:
        child.kill()  # TerminateProcess: no cleanup, no STOP event
        child.wait(timeout=10)

    conn = connect(db)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    spans = ActivityRepository(conn).spans_between(0, 2**62)
    conn.close()
    assert len(spans) == 1 and spans[0].duration_ms >= 500

    rec = ActivityRecorder(db, Probe())
    rec.start(run_thread=False)
    rec.stop()
    conn = connect(db)
    types = [r["type"] for r in ActivityRepository(conn).events_between(0, 2**62)]
    conn.close()
    assert types[-3:] == [SystemEvent.RECOVERED, SystemEvent.START, SystemEvent.STOP]
