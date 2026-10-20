"""Zip the browser extension for the Chrome Web Store and Edge Add-ons.

    uv run python scripts/package_extension.py

Writes ``dist/focuslab-extension-<version>.zip``. The stores assign their own item ID and reject
a manifest ``key``, so it is removed here; the repository manifest keeps it for a stable
unpacked ID. After publishing, put each store's item ID in ``focuslab.browser.STORE_IDS``.
"""

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "browser_extension"
FILES = ("background.js", "logic.js")


def main() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text("utf-8"))
    manifest.pop("key", None)
    out = ROOT / "dist" / f"focuslab-extension-{manifest['version']}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for name in FILES:
            z.write(EXTENSION / name, name)
        for icon in sorted((EXTENSION / "icons").glob("*.png")):
            z.write(icon, f"icons/{icon.name}")
    print(f"Built {out}")


if __name__ == "__main__":
    main()
