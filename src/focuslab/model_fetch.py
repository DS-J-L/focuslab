"""Explicit, user-run download of the MediaPipe face model with SHA256 verification.

FocusLab never downloads anything on its own; run ``focuslab --fetch-models``.
"""

import hashlib
import tempfile
import urllib.request
from pathlib import Path

from focuslab.config import FACE_MODEL_FILENAME, FROZEN, REPO_MODEL_DIR, data_dir

FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_dir() -> Path:
    """Repo assets/models in a source checkout, otherwise the user's data folder."""
    if not FROZEN and REPO_MODEL_DIR.parent.is_dir():  # never write into the install folder
        return REPO_MODEL_DIR
    return data_dir() / "models"


def fetch_face_model(dest_dir: Path | None = None) -> Path:
    dest_dir = dest_dir or target_dir()
    dest = dest_dir / FACE_MODEL_FILENAME
    if dest.is_file() and sha256(dest) == FACE_MODEL_SHA256:
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest_dir, suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        urllib.request.urlretrieve(FACE_MODEL_URL, tmp_path)
        actual = sha256(tmp_path)
        if actual != FACE_MODEL_SHA256:
            raise ValueError(f"checksum mismatch: {actual}")
        tmp_path.replace(dest)
    finally:
        tmp_path.unlink(missing_ok=True)
    return dest
