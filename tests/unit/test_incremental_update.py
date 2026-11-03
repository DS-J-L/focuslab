import functools
import hashlib
import json
import os
import random
import shutil
import stat
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from focuslab import update_manifest as index
from focuslab import updater
from focuslab.update_smoke import run


@pytest.fixture
def delivery(tmp_path):
    old, new, assets = (tmp_path / p for p in ("installed", "new", "assets"))
    for folder in (old, new):
        (folder / "_internal").mkdir(parents=True)
        (folder / "_internal/runtime.dll").write_bytes(random.Random(3).randbytes(1024 * 1024))
    (old / "FocusLab.exe").write_bytes(b"old exe")
    (old / "obsolete.dll").write_bytes(b"remove me")
    (new / "FocusLab.exe").write_bytes(random.Random(4).randbytes(16384))
    (new / "_internal/앵무새.png").write_bytes(b"new image")
    (new / "_internal/empty.txt").touch()
    archive, checksum, manifest, manifest_sha = index.package(new, assets, "0.3.0")
    state = {"mode": "range", "requests": [], "range_bytes": 0}

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            header = self.headers.get("Range")
            state["requests"].append((self.path, header))
            if not header or state["mode"] == "ignore":
                try:
                    return super().do_GET()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
            start, end = map(int, header.removeprefix("bytes=").split("-"))
            with archive.open("rb") as stream:
                stream.seek(start)
                data = stream.read(end - start + 1)
            self.send_response(206)
            actual_end = end + 1 if state["mode"] == "bad-range" else end
            content_range = f"bytes {start}-{actual_end}/{archive.stat().st_size}"
            self.send_header("Content-Range", content_range)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if state["mode"] == "corrupt":
                data = b"\x00" * len(data)
            if state["mode"] == "truncate":
                data = data[:len(data) // 2]
            self.wfile.write(data)
            state["range_bytes"] += len(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0),
                                 functools.partial(Handler, directory=str(assets)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    release = updater.Release("0.3.0", "", f"{url}/{archive.name}", f"{url}/{checksum.name}",
                              f"{url}/{manifest.name}", f"{url}/{manifest_sha.name}")
    state.update(old=old, new=new, assets=assets, archive=archive, checksum=checksum,
                 manifest=manifest, manifest_sha=manifest_sha, release=release,
                 dest=tmp_path / "downloads")
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def prepare(d, **kwargs):
    return updater.prepare(d["release"], d["dest"], d["old"], **kwargs)


def assert_complete(d, staged):
    paths = {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
    expected = {p.relative_to(d["new"]).as_posix() for p in d["new"].rglob("*") if p.is_file()}
    assert paths == expected
    assert all((staged / p).read_bytes() == (d["new"] / p).read_bytes() for p in paths)
    assert (d["old"] / "FocusLab.exe").read_bytes() == b"old exe"
    assert (d["old"] / "obsolete.dll").exists()


def edit_manifest(d, change):
    doc = json.loads(d["manifest"].read_bytes())
    change(doc)
    raw = json.dumps(doc).encode()
    d["manifest"].write_bytes(raw)
    d["manifest_sha"].write_text(hashlib.sha256(raw).hexdigest())


def test_downloads_only_changed_entries_and_removes_obsolete_files(delivery):
    d = delivery
    phases = []
    staged = prepare(d, progress=lambda *p: phases.append(p))
    assert_complete(d, staged)
    parsed = index.parse(d["manifest"].read_bytes(), "0.3.0")
    changed = [f for f in parsed.files if f.path != "_internal/runtime.dll"]
    assert d["range_bytes"] == sum(f.compressed_size for f in changed)
    assert d["range_bytes"] < d["archive"].stat().st_size / 50
    assert not any(path.endswith(".zip") and not r for path, r in d["requests"])
    assert not d["dest"].exists()  # no full ZIP or cache was downloaded
    assert phases[-1] == ("verify", len(parsed.files), len(parsed.files))


def test_same_size_damaged_local_file_is_downloaded(delivery):
    d = delivery
    (d["old"] / "_internal/runtime.dll").write_bytes(b"!" * 1024 * 1024)
    assert_complete(d, prepare(d))
    # Most bytes changed: one verified full transfer is quicker than many ranges.
    assert any(path.endswith(".zip") and not r for path, r in d["requests"])


def test_copy_fallback_when_filesystem_cannot_hardlink(delivery, monkeypatch):
    def denied(*args):
        raise OSError("hard links unavailable")
    monkeypatch.setattr(os, "link", denied)
    assert_complete(delivery, prepare(delivery))


def test_matching_bundle_needs_only_metadata_and_no_zip_bytes(delivery):
    d = delivery
    for path in d["new"].rglob("*"):
        if path.is_file():
            shutil.copyfile(path, d["old"] / path.relative_to(d["new"]))
    staged = prepare(d)
    assert not any(path.endswith(".zip") for path, _ in d["requests"])
    assert not (staged / "obsolete.dll").exists()
    assert index.sha256(staged / "FocusLab.exe") == index.sha256(d["new"] / "FocusLab.exe")


def test_local_disk_error_does_not_waste_a_full_redownload(delivery, monkeypatch):
    def denied(*args):
        raise PermissionError("disk cannot be written")
    monkeypatch.setattr(os, "link", denied)
    monkeypatch.setattr(shutil, "copyfile", denied)
    with pytest.raises(PermissionError):
        prepare(delivery)
    assert not any(path.endswith(".zip") for path, _ in delivery["requests"])
    assert not delivery["old"].with_name(".installed-update").exists()


@pytest.mark.parametrize("mode", ["ignore", "bad-range", "truncate", "corrupt"])
def test_transport_failure_falls_back_once_to_verified_full_zip(delivery, mode):
    d = delivery
    d["mode"] = mode
    phases = []
    assert_complete(d, prepare(d, progress=lambda *p: phases.append(p)))
    assert ("fallback", 0, 0) in phases
    assert sum(path.endswith(".zip") and not r for path, r in d["requests"]) == 1
    assert not list(d["dest"].iterdir())


@pytest.mark.parametrize("change", [
    lambda doc: doc.update(schema=2),
    lambda doc: doc.update(version="0.9.0"),
    lambda doc: doc["files"][0].update(path="../escape.exe"),
    lambda doc: doc["files"][0].update(compression=99),
    lambda doc: doc["files"][0].update(size=1),  # bounds decompression before hashing
    lambda doc: doc["files"][0].update(sha256="0" * 64),
    lambda doc: doc["files"][0].update(offset=doc["files"][0]["offset"] + 1),
])
def test_invalid_index_or_file_hash_uses_full_zip(delivery, change):
    edit_manifest(delivery, change)
    assert_complete(delivery, prepare(delivery))
    assert sum(path.endswith(".zip") and not r for path, r in delivery["requests"]) == 1


def test_unverified_index_is_never_used(delivery):
    d = delivery
    d["manifest_sha"].write_text("0" * 64)
    assert_complete(d, prepare(d))
    assert not d["range_bytes"]


def test_legacy_releases_keep_full_zip_compatibility(delivery):
    d = delivery
    release = d["release"]
    d["release"] = updater.Release(release.version, "", release.zip_url, release.sha256_url)
    assert_complete(d, prepare(d))
    assert not d["range_bytes"]
    assert all("manifest" not in path for path, _ in d["requests"])


@pytest.mark.parametrize("phase", ["check", "download", "verify"])
def test_cancellation_cleans_stage_without_fallback_or_install(delivery, phase):
    d = delivery
    stop = False

    def progress(step, done, total):
        nonlocal stop
        if step == phase and done:
            stop = True

    with pytest.raises(updater.UpdateCancelled):
        prepare(d, progress=progress, cancelled=lambda: stop)
    assert (d["old"] / "FocusLab.exe").read_bytes() == b"old exe"
    assert not d["old"].with_name(".installed-update").exists()
    assert not any(path.endswith(".zip") and not r for path, r in d["requests"])


def test_failed_full_fallback_leaves_running_installation_intact(delivery):
    d = delivery
    d["mode"] = "corrupt"
    d["checksum"].write_text("0" * 64)
    with pytest.raises(ValueError, match="checksum mismatch"):
        prepare(d)
    assert not d["old"].with_name(".installed-update").exists()
    assert not list(d["dest"].iterdir())
    assert (d["old"] / "FocusLab.exe").read_bytes() == b"old exe"


@pytest.mark.parametrize("path", ["../x", "/x", "a//b", "a/./b", "a\\b", "a:b",
                                    "CON", "com1.txt", "x.", "x ", "a/..", "a\x00b"])
def test_windows_unsafe_paths_are_rejected(path):
    with pytest.raises(ValueError):
        index.safe_path(path)


def test_case_aliases_and_file_directory_collisions_are_rejected(delivery):
    raw = json.loads(delivery["manifest"].read_bytes())
    raw["files"].append({**raw["files"][0], "path": "FOCUSLAB.EXE"})
    with pytest.raises(ValueError, match="duplicate"):
        index.parse(json.dumps(raw).encode(), "0.3.0")
    raw["files"][-1]["path"] = "_internal"
    with pytest.raises(ValueError, match="layout"):
        index.parse(json.dumps(raw).encode(), "0.3.0")


def test_staging_link_cannot_escape_install_parent(delivery, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep")
    staged = delivery["old"].with_name(".installed-update")
    try:
        staged.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="links"):
        prepare(delivery)
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("tag,expected", [(0x9000001A, False), (0xA0000003, True),
                                         (0xA000000C, True)])
def test_cloud_placeholders_are_allowed_but_redirecting_reparse_points_are_not(tag, expected):
    class ReparsePath:
        def lstat(self):
            class Info:
                st_mode = stat.S_IFDIR
                st_reparse_tag = tag
            return Info()
    assert index.is_link(ReparsePath()) is expected


def test_existing_bundle_change_during_staging_is_detected(delivery, monkeypatch):
    d = delivery
    original_link = os.link

    def tamper(source, dest):
        original_link(source, dest)
        if str(source).endswith("runtime.dll"):
            # Simulate an external writer after the initial installed-file hash.
            with open(source, "r+b") as stream:
                stream.write(b"damage")

    monkeypatch.setattr(os, "link", tamper)
    assert_complete(d, prepare(d))  # final verification must force verified full fallback
    assert any(path.endswith(".zip") and not r for path, r in d["requests"])


def test_release_index_maps_exact_compressed_zip_bytes(delivery):
    d = delivery
    with zipfile.ZipFile(d["archive"]) as z:
        assert z.read("FocusLab/FocusLab.exe") == (d["new"] / "FocusLab.exe").read_bytes()
    parsed = index.parse(d["manifest"].read_bytes(), "0.3.0")
    assert parsed.archive_sha256 == index.sha256(d["archive"])
    modern = updater.parse_release({"tag_name": "v0.3.0", "assets": [
        {"name": p.name, "browser_download_url": p.as_uri()} for p in
        (d["archive"], d["checksum"], d["manifest"], d["manifest_sha"])]})
    assert modern.manifest_url == d["manifest"].as_uri()


def test_source_transport_smoke_reports_measured_savings(tmp_path):
    report = tmp_path / "report.json"
    assert run(report) == 0
    measured = json.loads(report.read_bytes())
    total = measured["changed_zip_bytes"] + measured["metadata_bytes"]
    assert total < measured["full_zip_bytes"] / 10
