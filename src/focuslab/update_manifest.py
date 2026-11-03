"""Versioned, verified file index for a normal, backwards-compatible release ZIP.

Offsets point to raw compressed ZIP entry data so a client can request only changed
files with HTTP Range. No extra per-file assets or old-version-specific patches.
"""

import hashlib
import json
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_MANIFEST = 8 * 1024 * 1024
MAX_FILES = 10000
MAX_PACKAGE = 16 * 1024**3
HASH = re.compile(r"[0-9a-f]{64}\Z")
DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
           *(f"lpt{i}" for i in range(1, 10))}


def archive_name(version: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[-+][a-zA-Z0-9.+-]+)?", version):
        raise ValueError("invalid release version")
    return f"FocusLab-{version}-win64.zip"


def manifest_name(version: str) -> str:
    return archive_name(version).removesuffix(".zip") + ".manifest.json"


def safe_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("invalid package path")
    for part in value.split("/"):
        if (not part or part in (".", "..") or part[-1] in " ."
                or any(ord(c) < 32 or c in '<>:"\\|?*' for c in part)
                or part.split(".")[0].casefold() in DEVICES):
            raise ValueError("unsafe package path")
    return value


def sha256(path: Path, cancelled=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(256 * 1024), b""):
            if cancelled:
                cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def is_link(path: Path) -> bool:
    """Include name-surrogate reparse points (junctions), but allow OneDrive placeholders."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_reparse_tag", 0) & 0x20000000  # Microsoft name-surrogate bit
    )


@dataclass(frozen=True)
class Entry:
    path: str
    size: int
    sha256: str
    offset: int
    compressed_size: int
    compression: int


@dataclass(frozen=True)
class Manifest:
    archive_size: int
    archive_sha256: str
    files: tuple[Entry, ...]


def parse(raw: bytes, version: str) -> Manifest:
    if len(raw) > MAX_MANIFEST:
        raise ValueError("manifest too large")
    doc = json.loads(raw)
    if doc["schema"] != 1 or doc["version"] != version:
        raise ValueError("unsupported manifest version")
    archive = doc["archive"]
    if archive["name"] != archive_name(version) or not HASH.fullmatch(archive["sha256"]):
        raise ValueError("invalid archive identity")
    size = archive["size"]
    if type(size) is not int or not 0 < size <= MAX_PACKAGE:
        raise ValueError("invalid archive size")
    records = doc["files"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_FILES:
        raise ValueError("invalid file count")
    files, names, directories, ranges = [], set(), set(), []
    for record in records:
        item = Entry(**record)
        name = safe_path(item.path).casefold()
        if name in names:
            raise ValueError("duplicate package path")
        names.add(name)
        directories.update(name.rsplit("/", i)[0] for i in range(1, name.count("/") + 1))
        if (any(type(n) is not int for n in
                (item.size, item.offset, item.compressed_size, item.compression))
                or not 0 <= item.size <= MAX_PACKAGE or item.offset < 30
                or item.compressed_size < 0 or item.offset + item.compressed_size > size
                or item.compression not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or (item.compression == zipfile.ZIP_STORED and item.size != item.compressed_size)
                or not HASH.fullmatch(item.sha256)):
            raise ValueError("invalid file record")
        if item.compressed_size:
            ranges.append((item.offset, item.offset + item.compressed_size))
        files.append(item)
    if (names & directories or "focuslab.exe" not in names
            or not any(name.startswith("_internal/") for name in names)
            or sum(f.size for f in files) > MAX_PACKAGE):
        raise ValueError("invalid application layout")
    ranges.sort()
    if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:], strict=False)):
        raise ValueError("overlapping file ranges")
    return Manifest(size, archive["sha256"], tuple(files))


def package(source: Path, output: Path, version: str) -> tuple[Path, ...]:
    """Build ZIP + SHA256 and a SHA256-protected index from the same bytes."""
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("release output must be outside the source bundle")
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(source.rglob("*"))
    if is_link(source) or any(is_link(path) for path in paths):
        raise ValueError("release source contains links")
    entries = []
    archive = output / archive_name(version)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in paths:
            if not path.is_file():
                continue
            name = safe_path(path.relative_to(source).as_posix())
            z.write(path, f"FocusLab/{name}")
            info = z.getinfo(f"FocusLab/{name}")
            entries.append({"path": name, "size": info.file_size, "sha256": sha256(path),
                            "offset": info.header_offset, "compressed_size": info.compress_size,
                            "compression": info.compress_type})
    with archive.open("rb") as stream:
        for entry in entries:
            stream.seek(entry["offset"])
            header = stream.read(30)
            name_len, extra_len = struct.unpack_from("<HH", header, 26)
            entry["offset"] += 30 + name_len + extra_len
    digest = sha256(archive)
    doc = {"schema": 1, "version": version,
           "archive": {"name": archive.name, "size": archive.stat().st_size, "sha256": digest},
           "files": entries}
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    parse(raw, version)  # fail packaging rather than publish an unusable index
    index = output / manifest_name(version)
    index.write_bytes(raw)
    result = []
    for path in (archive, index):
        checksum = path.with_name(path.name + ".sha256")
        checksum.write_text(f"{sha256(path)}  {path.name}\n", encoding="ascii")
        result.extend((path, checksum))
    return tuple(result)
