"""Opt-in updates from GitHub Releases for the packaged FocusLab.exe.

Nothing here runs on its own: the Settings page calls it when the user presses "Check now",
or at startup only after the user turned on "Check for updates when FocusLab starts".
A check is one request to the GitHub API; an update downloads the release zip, verifies its
SHA256, unpacks it next to the install folder and swaps the folders after FocusLab exits.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from focuslab import __version__
from focuslab.config import FROZEN

REPO = "DS-J-L/focuslab"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
EXE_NAME = "FocusLab.exe"
TIMEOUT_S = 15


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    zip_url: str | None
    sha256_url: str | None


def asset_name(version: str) -> str:
    return f"FocusLab-{version}-win64.zip"


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.2.0' -> (0, 2, 0); anything after a '-' or '+' (pre-release, build) is ignored."""
    core = text.strip().lstrip("vV").split("-")[0].split("+")[0]
    return tuple(int(part) for part in core.split("."))


def is_newer(release: Release, current: str = __version__) -> bool:
    return parse_version(release.version) > parse_version(current)


def _open(url: str, accept: str = "application/octet-stream"):
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": f"FocusLab/{__version__}"}
    )
    return urllib.request.urlopen(request, timeout=TIMEOUT_S)


def parse_release(data: dict) -> Release:
    version = data["tag_name"].lstrip("vV")
    urls = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    name = asset_name(version)
    return Release(
        version=version,
        page_url=data.get("html_url") or RELEASES_PAGE,
        zip_url=urls.get(name),
        sha256_url=urls.get(f"{name}.sha256"),
    )


def latest_release(url: str = LATEST_URL) -> Release:
    with _open(url, "application/vnd.github+json") as response:
        return parse_release(json.load(response))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> bool:
    """Only a packaged folder build can replace itself; a source checkout updates with git."""
    if not (FROZEN and sys.platform == "win32"):
        return False
    folder = install_dir()
    return (folder / EXE_NAME).is_file() and (folder / "_internal").is_dir()


def download(
    release: Release, dest_dir: Path, progress: Callable[[int], None] | None = None
) -> Path:
    """Download the release zip into dest_dir and verify it against the published SHA256."""
    if not (release.zip_url and release.sha256_url):
        raise ValueError("this release has no Windows package")
    with _open(release.sha256_url) as response:
        expected = response.read().decode("ascii").split()[0].lower()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / asset_name(release.version)
    with tempfile.NamedTemporaryFile(dir=dest_dir, suffix=".part", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            digest = hashlib.sha256()
            with _open(release.zip_url) as response:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    tmp.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done * 100 // total)
        except BaseException:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise
    if digest.hexdigest() != expected:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch: {digest.hexdigest()}")
    tmp_path.replace(dest)
    return dest


def _long(path: Path) -> Path:
    """Extended-length form on Windows: the bundle's deepest files (numpy licenses) pass
    260 characters while unpacking in a deep folder unless long paths are enabled."""
    if sys.platform != "win32" or str(path).startswith("\\\\?\\"):
        return path
    return Path("\\\\?\\" + str(path.resolve()))


def stage(zip_path: Path, target: Path) -> Path:
    """Unpack the zip's FocusLab folder next to the install folder (same volume, so the
    later swap is two renames). Returns the unpacked folder that holds FocusLab.exe."""
    staged = target.with_name(f".{target.name}-update")
    shutil.rmtree(_long(staged), ignore_errors=True)
    with tempfile.TemporaryDirectory(dir=_long(target.parent)) as unpack:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(unpack)  # extractall drops absolute and '..' member paths
        roots = [p.parent for p in Path(unpack).rglob(EXE_NAME)]
        if len(roots) != 1 or not (roots[0] / "_internal").is_dir():
            raise ValueError("the package does not contain one FocusLab folder")
        roots[0].replace(_long(staged))
    return staged


def _ps(text: str | Path) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def swap_script(staged: Path, target: Path, pid: int) -> str:
    """PowerShell run after FocusLab exits: rename the install folder aside, move the staged
    folder into its place and start the new exe. If the install folder stays locked (for
    example by a browser still connected to the native host) the old version starts again."""
    old = target.with_name(f"{target.name}.old")
    return f"""
$target = {_ps(target)}; $name = {_ps(target.name)}
$staged = {_ps(staged)}; $old = {_ps(old)}; $exe = {_ps(target / EXE_NAME)}
Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {{
  try {{ Rename-Item -LiteralPath $target -NewName "$name.old" -ErrorAction Stop; $ok = $true }}
  catch {{ Start-Sleep -Seconds 1 }}
}}
if ($ok) {{
  try {{ Rename-Item -LiteralPath $staged -NewName $name -ErrorAction Stop }}
  catch {{ Rename-Item -LiteralPath $old -NewName $name; $ok = $false }}
}}
Start-Process -FilePath $exe
if ($ok) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
"""


def launch_swap(staged: Path, target: Path, pid: int) -> None:
    """Start the swap helper detached; the caller must quit right after."""
    shutil.rmtree(_long(target.with_name(f"{target.name}.old")), ignore_errors=True)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            swap_script(staged, target, pid),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
