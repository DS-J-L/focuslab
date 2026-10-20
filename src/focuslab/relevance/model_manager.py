"""Optional local language model for semantic relevance: install, verify, locate and remove.

Nothing is downloaded until the user turns the feature on in Settings and confirms. Files
come from one pinned upstream revision of intfloat/multilingual-e5-small (MIT) and are
verified by SHA256 before they are used. Without the model, relevance runs on rules only.
"""

import hashlib
import importlib.util
import os
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from focuslab.config import REPO_MODEL_DIR, data_dir
from focuslab.model_fetch import target_dir

UPSTREAM = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_VERSION = f"multilingual-e5-small-qint8@{REVISION[:7]}"
LICENSE = "MIT"
_BASE = f"https://huggingface.co/{UPSTREAM}/resolve/{REVISION}/onnx/"
SUBDIR = "relevance"


@dataclass(frozen=True)
class ModelFile:
    name: str  # local file name
    url: str
    sha256: str
    size: int


MODEL_FILE = ModelFile(
    "multilingual-e5-small-qint8.onnx",
    _BASE + "model_qint8_avx512_vnni.onnx",
    "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88",
    118_346_824,
)
TOKENIZER_FILE = ModelFile(
    "sentencepiece.bpe.model",
    _BASE + "sentencepiece.bpe.model",
    "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    5_069_051,
)
FILES = (MODEL_FILE, TOKENIZER_FILE)
DOWNLOAD_BYTES = sum(f.size for f in FILES)


class ModelStatus(StrEnum):
    READY = "READY"
    NOT_INSTALLED = "NOT_INSTALLED"
    RUNTIME_MISSING = "RUNTIME_MISSING"  # onnxruntime or sentencepiece is not installed


class InstallCancelled(Exception):
    pass


def runtime_available() -> bool:
    return all(importlib.util.find_spec(m) for m in ("onnxruntime", "sentencepiece"))


def search_dirs() -> list[Path]:
    """Where an installed model may be: FOCUSLAB_MODEL_DIR, repo assets, the data folder."""
    dirs = [Path(d) / SUBDIR for d in [os.environ.get("FOCUSLAB_MODEL_DIR")] if d]
    return [*dirs, REPO_MODEL_DIR / SUBDIR, data_dir() / "models" / SUBDIR]


def installed_dir(dirs: list[Path] | None = None) -> Path | None:
    """First folder holding every file at its expected size (checksums are verified on load)."""
    for d in search_dirs() if dirs is None else dirs:
        if all((d / f.name).is_file() and (d / f.name).stat().st_size == f.size for f in FILES):
            return d
    return None


def status(dirs: list[Path] | None = None) -> ModelStatus:
    if not runtime_available():
        return ModelStatus.RUNTIME_MISSING
    return ModelStatus.READY if installed_dir(dirs) else ModelStatus.NOT_INSTALLED


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(folder: Path) -> None:
    """Raise ValueError unless every file matches its pinned checksum."""
    for f in FILES:
        actual = sha256(folder / f.name)
        if actual != f.sha256:
            raise ValueError(f"checksum mismatch for {f.name}: {actual}")


Progress = Callable[[int, int], None]  # (bytes done, bytes total)


def install(
    dest: Path | None = None,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    opener: Callable[[str], object] = urllib.request.urlopen,
) -> Path:
    """Download and verify every file into ``dest``; a failed or cancelled file is removed."""
    dest = dest or target_dir() / SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    done = 0
    for f in FILES:
        target = dest / f.name
        if target.is_file() and target.stat().st_size == f.size and sha256(target) == f.sha256:
            done += f.size
            continue
        with tempfile.NamedTemporaryFile(dir=dest, suffix=".part", delete=False) as tmp:
            part = Path(tmp.name)
        try:
            digest = hashlib.sha256()
            with opener(f.url) as response, part.open("wb") as out:
                for chunk in iter(lambda: response.read(1 << 16), b""):
                    if cancel is not None and cancel.is_set():
                        raise InstallCancelled()
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, DOWNLOAD_BYTES)
            if digest.hexdigest() != f.sha256:
                raise ValueError(f"checksum mismatch for {f.name}: {digest.hexdigest()}")
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)
    return dest


def remove(dirs: list[Path] | None = None) -> int:
    """Delete the model files (and only those) wherever they are; returns how many."""
    removed = 0
    for d in search_dirs() if dirs is None else dirs:
        for f in FILES:
            path = d / f.name
            if path.is_file():
                path.unlink()
                removed += 1
    return removed


def load(folder: Path):
    """Verify the files, then open them (slow: run on the analyzer's worker thread)."""
    from focuslab.relevance.embedding import OnnxEmbedder

    verify(folder)
    return OnnxEmbedder(folder)
