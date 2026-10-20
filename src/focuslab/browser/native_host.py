"""Native Messaging host launched by Chrome/Edge for the FocusLab extension.

Chrome starts this process with the caller's origin as the first argument and talks over
stdin/stdout. Only the FocusLab extension origin is served; every message is validated and
stored as the latest state for that browser profile. When the browser closes the pipe the
profile's state is removed so no stale "current site" remains. Nothing is logged to stderr
(Chrome may write it to its own log).
"""

import sys
import time
from pathlib import Path

from focuslab.browser import EXTENSION_ORIGINS
from focuslab.browser.install import bound_data_dir
from focuslab.browser.protocol import ProtocolError, parse_state, read_message, write_message
from focuslab.browser.store import BrowserStateStore
from focuslab.config import data_dir, db_path
from focuslab.storage.sqlite_db import connect

MAX_INVALID = 20


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _parse_args(argv: list[str]) -> tuple[str, Path | None]:
    origin, folder = "", None
    args = iter(argv)
    for arg in args:
        if arg == "--data-dir":
            folder = Path(next(args, ""))
        elif arg.startswith("chrome-extension://"):
            origin = arg
    return origin, folder


def serve(stdin, stdout, origin: str, database: Path) -> int:
    if origin not in EXTENSION_ORIGINS:
        write_message(stdout, {"type": "error", "error": "origin not allowed"})
        return 1
    conn = connect(database)
    store = BrowserStateStore(conn)
    store.purge_stale(_now_ms())
    seen: set[tuple[str, str]] = set()
    invalid = 0
    try:
        while True:
            try:
                message = read_message(stdin)
            except ProtocolError as exc:  # framing is lost: the stream cannot be trusted
                write_message(stdout, {"type": "error", "error": str(exc)})
                return 2
            if message is None:
                return 0
            try:
                state = parse_state(message)
            except ProtocolError as exc:
                invalid += 1
                write_message(stdout, {"type": "error", "error": str(exc)})
                if invalid >= MAX_INVALID:
                    return 2
                continue
            seen.add((state.browser, state.instance))
            stored = store.apply(state, _now_ms())
            response = {"type": "ack", "seq": state.seq, "stored": stored}
            if store.title_allowed():
                response["title_allowed"] = True
            write_message(stdout, response)
    finally:
        for browser, instance in seen:
            store.clear(browser, instance)
        conn.close()


def main(argv: list[str] | None = None) -> int:
    origin, folder = _parse_args(sys.argv[1:] if argv is None else argv)
    folder = folder or bound_data_dir() or data_dir()
    return serve(sys.stdin.buffer, sys.stdout.buffer, origin, db_path(folder))


if __name__ == "__main__":
    sys.exit(main())
