"""Register the native messaging host for Chrome and Edge (per user, no admin rights).

``HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.focuslab.activity`` (and the Edge
equivalent) points at a manifest in the data folder. The manifest allows only the FocusLab
extension origin and names the host executable. The host finds its data folder again through
the same registry value, so a custom ``--data-dir`` keeps working.
"""

import json
import sys
from pathlib import Path

from focuslab.browser import EXTENSION_ORIGINS, HOST_NAME
from focuslab.config import data_dir

REGISTRY_KEYS = {
    "chrome": rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}",
    "edge": rf"Software\Microsoft\Edge\NativeMessagingHosts\{HOST_NAME}",
}
MANIFEST_NAME = f"{HOST_NAME}.json"
HOST_FOLDER = "browser-host"
SCRIPT_NAME = "focuslab-native-host.exe"  # console script from pyproject.toml


def host_executable() -> Path:
    """The packaged app handles the origin argument itself; dev installs use the script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.executable).with_name(SCRIPT_NAME)


def manifest(executable: Path) -> dict:
    return {
        "name": HOST_NAME,
        "description": "FocusLab activity bridge (receives the active tab hostname only)",
        "path": str(executable),
        "type": "stdio",
        "allowed_origins": list(EXTENSION_ORIGINS),
    }


def manifest_path(folder: Path | None = None) -> Path:
    return (folder or data_dir()) / HOST_FOLDER / MANIFEST_NAME


def install(folder: Path | None = None, keys: dict[str, str] = REGISTRY_KEYS) -> Path:
    import winreg

    executable = host_executable()
    if not executable.exists():
        raise FileNotFoundError(f"native host not found: {executable} (run: uv sync)")
    path = manifest_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest(executable), indent=2), encoding="utf-8")
    for key in keys.values():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, str(path))
    return path


def uninstall(folder: Path | None = None, keys: dict[str, str] = REGISTRY_KEYS) -> None:
    if sys.platform == "win32":
        import winreg

        for key in keys.values():
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError:
                pass
    manifest_path(folder).unlink(missing_ok=True)


def _registered_manifest(key: str) -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "")
    except OSError:
        return None
    path = Path(value)
    return path if path.is_file() else None


def registered(keys: dict[str, str] = REGISTRY_KEYS) -> dict[str, bool]:
    return {browser: _registered_manifest(key) is not None for browser, key in keys.items()}


def bound_data_dir(keys: dict[str, str] = REGISTRY_KEYS) -> Path | None:
    """Data folder of the registered manifest (``<data>/browser-host/<manifest>``)."""
    for key in keys.values():
        path = _registered_manifest(key)
        if path is not None:
            return path.parent.parent
    return None
