import base64
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import pytest

from focuslab.browser import EXTENSION_ID, EXTENSION_ORIGIN
from focuslab.browser.protocol import (
    MAX_MESSAGE_BYTES,
    BrowserState,
    ProtocolError,
    parse_state,
    read_message,
    write_message,
)
from focuslab.browser.store import BrowserStateStore
from focuslab.storage.repository import Repository
from focuslab.storage.sqlite_db import connect

ROOT = Path(__file__).resolve().parents[2]


def msg(**over):
    base = {"v": 1, "type": "state", "browser": "chrome", "instance": "abc-1", "seq": 1,
            "ts": 1, "focused": True, "domain": "github.com"}
    base.update(over)
    return base


def frame(obj) -> bytes:
    body = json.dumps(obj).encode()
    return struct.pack("<I", len(body)) + body


def test_extension_id_matches_the_manifest_key():
    manifest = json.loads((ROOT / "browser_extension" / "manifest.json").read_text("utf-8"))
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == EXTENSION_ID
    assert manifest["incognito"] == "not_allowed"
    assert sorted(manifest["permissions"]) == ["alarms", "nativeMessaging", "tabs"]
    assert "host_permissions" not in manifest


def test_framing_roundtrip_and_limits():
    out = io.BytesIO()
    write_message(out, {"type": "ack", "seq": 3})
    assert read_message(io.BytesIO(out.getvalue())) == {"type": "ack", "seq": 3}
    assert read_message(io.BytesIO(b"")) is None
    for bad in (b"\x01\x00", struct.pack("<I", MAX_MESSAGE_BYTES + 1) + b"x",
                struct.pack("<I", 10) + b"{}", struct.pack("<I", 3) + b"abc",
                frame([1, 2]), struct.pack("<I", 0)):
        with pytest.raises(ProtocolError):
            read_message(io.BytesIO(bad))


def test_state_schema_is_strict():
    assert parse_state(msg()) == BrowserState("chrome", "abc-1", 1, 1, True, "github.com")
    assert parse_state(msg(focused=False)).domain is None  # unfocused never carries a site
    assert parse_state(msg(domain=None)).domain is None
    assert parse_state(msg(domain="localhost")).domain == "localhost"
    rejected = [
        msg(url="https://github.com/a"), {k: v for k, v in msg().items() if k != "seq"},
        msg(v=2), msg(type="history"), msg(browser="firefox"), msg(instance="x" * 65),
        msg(instance="../etc"), msg(seq=-1), msg(seq=True), msg(ts="now"), msg(focused="yes"),
        msg(domain="https://github.com"), msg(domain="github.com/path"), msg(domain="GitHub.com"),
        msg(domain="-bad.com"), msg(domain="a" * 254), msg(domain=""), msg(domain=5),
    ]
    for message in rejected:
        with pytest.raises(ProtocolError):
            parse_state(message)


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "b.db")
    repo = Repository(conn)
    for key in ("consent.recording", "consent.browser"):
        repo.set_setting(key, "1")
    yield BrowserStateStore(conn), repo
    conn.close()


def rows(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT browser, instance, seq, focused, domain FROM browser_state ORDER BY browser")]


def test_store_applies_in_sequence_order_only(store):
    st, repo = store
    assert st.apply(BrowserState("chrome", "i", 5, 0, True, "github.com"), 1000)
    st.apply(BrowserState("chrome", "i", 4, 0, True, "youtube.com"), 1001)  # late duplicate
    st.apply(BrowserState("chrome", "i", 5, 0, True, "youtube.com"), 1002)  # replay
    assert rows(repo.conn) == [("chrome", "i", 5, 1, "github.com")]
    st.apply(BrowserState("chrome", "j", 1, 0, True, "docs.python.org"), 1003)  # new worker
    assert len(rows(repo.conn)) == 2
    assert st.last_report_ms() == 1003


@pytest.mark.parametrize("key,value", [
    ("consent.browser", "0"), ("consent.recording", "0"), ("activity.paused", "1"),
])
def test_store_writes_nothing_without_consent_or_while_paused(store, key, value):
    st, repo = store
    st.apply(BrowserState("edge", "i", 1, 0, True, "github.com"), 1000)
    repo.set_setting(key, value)
    assert st.apply(BrowserState("edge", "i", 2, 0, True, "youtube.com"), 1001) is False
    assert rows(repo.conn) == []  # the earlier state is removed too


def test_repository_returns_the_most_recently_focused_profile(store):
    from focuslab.storage.activity_repository import ActivityRepository

    st, repo = store
    st.apply(BrowserState("chrome", "a", 1, 0, True, "github.com"), 1000)
    st.apply(BrowserState("chrome", "b", 1, 0, True, "youtube.com"), 2000)
    st.apply(BrowserState("chrome", "b", 2, 0, False, None), 3000)  # profile b lost focus
    activity = ActivityRepository(repo.conn)
    assert activity.browser_domain("chrome", 0) == "github.com"
    assert activity.browser_domain("chrome", 1500) is None  # a's report is too old
    assert activity.browser_domain("edge", 0) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_install_registers_both_browsers_and_binds_the_data_folder(tmp_path):
    from focuslab.browser import install

    keys = {"chrome": r"Software\FocusLab-tests\Chrome\com.focuslab.activity",
            "edge": r"Software\FocusLab-tests\Edge\com.focuslab.activity"}
    try:
        path = install.install(tmp_path, keys)
        manifest = json.loads(path.read_text("utf-8"))
        assert manifest["allowed_origins"] == [EXTENSION_ORIGIN]
        assert manifest["type"] == "stdio" and Path(manifest["path"]).is_file()
        assert install.registered(keys) == {"chrome": True, "edge": True}
        assert install.bound_data_dir(keys) == tmp_path
        install.uninstall(tmp_path, keys)
        assert install.registered(keys) == {"chrome": False, "edge": False}
        assert not path.exists()
    finally:
        import winreg

        for sub in (*keys.values(), r"Software\FocusLab-tests\Chrome",
                    r"Software\FocusLab-tests\Edge", r"Software\FocusLab-tests"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
