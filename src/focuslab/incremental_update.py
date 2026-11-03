"""Fetch changed compressed entries from a release ZIP using verified byte ranges."""

import hashlib
import os
import shutil
import zlib
from pathlib import Path

from focuslab import update_manifest as index
from focuslab import updater as u


def _small(url: str, limit: int, cancelled) -> bytes:
    u._check(cancelled)
    with u._open(url) as response:
        data = response.read(limit + 1)
    u._check(cancelled)
    if len(data) > limit:
        raise ValueError("update metadata too large")
    return data


def _manifest(release: u.Release, cancelled) -> index.Manifest:
    raw = _small(release.manifest_url, index.MAX_MANIFEST, cancelled)
    expected = _small(release.manifest_sha256_url, 1024, cancelled).decode("ascii").split()[0]
    if hashlib.sha256(raw).hexdigest() != expected.lower():
        raise ValueError("manifest checksum mismatch")
    return index.parse(raw, release.version)


def _regular(path: Path, root: Path) -> bool:
    """Never read through installed reparse points when reusing immutable bundle files."""
    try:
        return path.is_file() and not any(index.is_link(p) for p in
                                         (path, *path.parents) if p.is_relative_to(root))
    except OSError:
        return False


def _entry(release, manifest, item, dest, advance, cancelled):
    digest = hashlib.sha256()
    written = 0
    inflater = zlib.decompressobj(-15) if item.compression == 8 else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        if item.compressed_size:
            start, end = item.offset, item.offset + item.compressed_size - 1
            with u._open(release.zip_url, headers={"Range": f"bytes={start}-{end}",
                                                 "Accept-Encoding": "identity"}) as response:
                # Close a 200 response before reading its body; do not accidentally
                # consume the entire ZIP once here and again during the fallback.
                if (response.status != 206
                        or response.headers.get("Content-Range") !=
                        f"bytes {start}-{end}/{manifest.archive_size}"
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                        or int(response.headers.get("Content-Length", item.compressed_size))
                        != item.compressed_size):
                    raise ValueError("server does not support exact ZIP byte ranges")
                remaining = item.compressed_size
                while remaining:
                    u._check(cancelled)
                    chunk = response.read(min(u.CHUNK, remaining))
                    if not chunk:
                        raise ValueError("incomplete file download")
                    remaining -= len(chunk)
                    advance(len(chunk))
                    data = (inflater.decompress(chunk, item.size - written + 1)
                            if inflater else chunk)
                    written += len(data)
                    if written > item.size:
                        raise ValueError("expanded file exceeds published size")
                    out.write(data)
                    digest.update(data)
        if (inflater and (not inflater.eof or inflater.unused_data or inflater.unconsumed_tail)):
            raise ValueError("invalid compressed file")
        if written != item.size or digest.hexdigest() != item.sha256:
            raise ValueError("file checksum mismatch")
    u._check(cancelled)


def stage_changed(release, target, emit, cancelled=None) -> Path:
    manifest = _manifest(release, cancelled)
    if not release.zip_url:
        raise ValueError("missing release ZIP")
    staged = u._staging_path(target)
    out = u._long(staged)
    out.mkdir(parents=True)
    def check():
        u._check(cancelled)

    try:
        changed = []
        count = len(manifest.files)
        emit("check", 0, count)
        for n, item in enumerate(manifest.files, 1):
            check()
            source, dest = u._long(target / item.path), out / item.path
            matched = False
            if _regular(source, u._long(target)):
                try:
                    matched = (source.stat().st_size == item.size
                               and index.sha256(source, check) == item.sha256)
                except OSError:
                    matched = False
            if matched:
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Bundle files are immutable. Linking avoids copying large runtimes;
                # fall back to a regular copy on filesystems that cannot hard-link.
                try:
                    os.link(source, dest)
                except OSError:
                    shutil.copyfile(source, dest)
            else:
                changed.append(item)
            emit("check", n, count)
        done, total = 0, sum(f.compressed_size for f in changed)
        if total >= manifest.archive_size * 0.85:
            raise ValueError("most package bytes changed; the full ZIP is faster")
        emit("download", 0, total)

        def advance(amount):
            nonlocal done
            done += amount
            emit("download", done, total)

        for item in changed:
            check()
            _entry(release, manifest, item, out / item.path, advance, cancelled)
        emit("verify", 0, count)
        for n, item in enumerate(manifest.files, 1):
            check()
            if index.sha256(out / item.path, check) != item.sha256:
                raise ValueError("staged file checksum mismatch")
            emit("verify", n, count)
        check()
        return staged
    except BaseException:
        u.discard(staged)
        raise
