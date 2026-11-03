"""Isolated transport smoke check, also executed inside the windowed frozen EXE.

Uses synthetic files and a loopback-only HTTP server. Never reads user data, launches
sensors, changes the installed application, or invokes the restart/swap helper.
"""

import functools
import json
import random
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from focuslab import update_manifest as index
from focuslab import updater


class RangeHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = Path(self.translate_path(self.path))
        header = self.headers.get("Range")
        if not header:
            return super().do_GET()
        start, end = map(int, header.removeprefix("bytes=").split("-"))
        with path.open("rb") as stream:
            stream.seek(start)
            data = stream.read(end - start + 1)
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{path.stat().st_size}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        self.server.transferred += len(data)


def run(report: Path) -> int:
    result = {}
    try:
        with tempfile.TemporaryDirectory(prefix="focuslab-update-check-") as folder:
            root = Path(folder)
            old, new, assets = root / "installed", root / "new", root / "assets"
            for base in (old, new):
                (base / "_internal").mkdir(parents=True)
            unchanged = random.Random(7).randbytes(4 * 1024 * 1024)
            for base in (old, new):
                (base / "_internal/runtime.dll").write_bytes(unchanged)
            (old / "FocusLab.exe").write_bytes(b"old synthetic exe")
            (old / "obsolete.txt").write_bytes(b"removed in new version")
            (new / "FocusLab.exe").write_bytes(random.Random(8).randbytes(64 * 1024))
            package, _, manifest, _ = index.package(new, assets, "99.0.0")
            handler = functools.partial(RangeHandler, directory=str(assets))
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.transferred = 0
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                release = updater.Release("99.0.0", "", f"{url}/{package.name}",
                                          f"{url}/{package.name}.sha256",
                                          f"{url}/{manifest.name}",
                                          f"{url}/{manifest.name}.sha256")
                staged = updater.prepare(release, root / "downloads", old)
                parsed = index.parse(manifest.read_bytes(), release.version)
                assert all(index.sha256(staged / f.path) == f.sha256 for f in parsed.files)
                assert (old / "FocusLab.exe").read_bytes() == b"old synthetic exe"
                assert not (staged / "obsolete.txt").exists()
                changed = next(f for f in parsed.files if f.path == "FocusLab.exe")
                assert server.transferred == changed.compressed_size
                assert server.transferred < package.stat().st_size / 10
                result = {"ok": True, "changed_zip_bytes": server.transferred,
                          "full_zip_bytes": package.stat().st_size,
                          "metadata_bytes": manifest.stat().st_size +
                          manifest.with_name(manifest.name + ".sha256").stat().st_size,
                          "unchanged_bytes_reused": len(unchanged)}
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("ok") else 1
