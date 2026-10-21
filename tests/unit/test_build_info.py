"""Which build is running, so a stale exe can be told apart from an updated one."""

import json
from datetime import datetime

from focuslab import __version__, build_info


def test_a_source_checkout_reports_its_git_commit():
    info = build_info.current()
    assert info is not None and not info.packaged
    assert len(info.commit) >= 7 and info.key == f"{__version__}+{info.commit}"
    assert info.committed.tzinfo is not None


def test_the_exe_reads_the_record_written_at_build_time(monkeypatch, tmp_path):
    record = tmp_path / build_info.BUILD_FILE
    record.write_text(json.dumps({"commit": "abc1234", "committed": "2026-10-21T14:02:00+09:00"}))
    monkeypatch.setattr(build_info, "files", lambda _pkg: tmp_path)
    monkeypatch.setattr(build_info, "FROZEN", True)
    info = build_info.current()
    assert info.packaged and info.commit == "abc1234"
    assert info.committed == datetime.fromisoformat("2026-10-21T14:02:00+09:00")
    record.write_text("damaged")
    assert build_info.current() is None
