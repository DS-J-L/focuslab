"""The real native host process, spoken to over stdio exactly like Chrome does."""

import json
import struct
import subprocess
import sys

import pytest

from focuslab.browser import EXTENSION_ORIGIN
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect


def frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return struct.pack("<I", len(body)) + body


def read(stream):
    (length,) = struct.unpack("<I", stream.read(4))
    return json.loads(stream.read(length))


def state(seq, domain, focused=True):
    return {"v": 1, "type": "state", "browser": "chrome", "instance": "w-1", "seq": seq,
            "ts": 0, "focused": focused, "domain": domain}


def host(folder, origin=EXTENSION_ORIGIN):
    return subprocess.Popen(
        [sys.executable, "-m", "focuslab.browser.native_host", origin, "--parent-window=0",
         "--data-dir", str(folder)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


@pytest.fixture
def consented(tmp_path):
    conn = connect(tmp_path / "focuslab.db")
    repo = Repository(conn)
    repo.set_setting("consent.recording", "1")
    repo.set_setting("consent.browser", "1")
    conn.close()
    return tmp_path


def browser_rows(folder):
    conn = connect(folder / "focuslab.db")
    out = [tuple(r) for r in conn.execute(
        "SELECT browser, seq, focused, domain FROM browser_state")]
    conn.close()
    return out


def send(proc, obj):
    proc.stdin.write(frame(obj))
    proc.stdin.flush()
    return read(proc.stdout)


def test_host_stores_validated_state_and_clears_it_when_the_browser_closes(consented):
    proc = host(consented)
    assert send(proc, state(1, "github.com")) == {"type": "ack", "seq": 1, "stored": True}
    assert browser_rows(consented) == [("chrome", 1, 1, "github.com")]
    leaked = {**state(2, "youtube.com"), "url": "https://youtube.com/watch"}
    assert send(proc, leaked)["type"] == "error"  # full URLs are refused, not stored
    assert send(proc, state(3, "youtube.com"))["stored"] is True
    assert browser_rows(consented) == [("chrome", 3, 1, "youtube.com")]
    proc.stdin.close()  # the browser quit
    assert proc.wait(timeout=10) == 0
    assert browser_rows(consented) == []
    assert proc.stderr.read() == b""  # nothing (no domains) is logged


def test_host_refuses_other_extensions(consented):
    proc = host(consented, origin="chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/")
    out, _ = proc.communicate(frame(state(1, "github.com")), timeout=10)
    assert proc.returncode == 1 and b"origin not allowed" in out
    assert browser_rows(consented) == []


def test_host_exits_on_oversized_or_broken_frames(consented):
    proc = host(consented)
    out, _ = proc.communicate(struct.pack("<I", 1_000_000) + b"x" * 100, timeout=10)
    assert proc.returncode == 2 and b"out of range" in out


def test_host_without_consent_stores_nothing(tmp_path):
    proc = host(tmp_path)
    assert send(proc, state(1, "github.com"))["stored"] is False
    proc.stdin.close()
    proc.wait(timeout=10)
    assert browser_rows(tmp_path) == []



def test_host_ack_grants_optional_titles_only_after_desktop_consent(consented):
    conn = connect(consented / "focuslab.db")
    Repository(conn).set_setting("consent.page_titles", "1")
    conn.close()
    proc = host(consented)
    response = send(proc, {**state(1, "youtube.com"), "title": "AR lecture"})
    assert response == {"type": "ack", "seq": 1, "stored": True, "title_allowed": True}
    conn = connect(consented / "focuslab.db")
    assert conn.execute("SELECT page_title FROM browser_state").fetchone()[0] == "AR lecture"
    conn.close()
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0
