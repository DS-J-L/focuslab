"""Native Messaging framing and strict validation of extension messages.

Chrome frames each message as a 4-byte native-endian (little-endian on Windows) length followed
by UTF-8 JSON. Anything that is not exactly the documented schema is rejected, so a buggy or
hostile sender cannot smuggle full URLs or oversized payloads into the database.
Optional page titles require explicit separate consent and strict validation.
"""

import json
import re
import struct
from dataclasses import dataclass
from typing import BinaryIO

MAX_MESSAGE_BYTES = 4096  # a valid state message is ~200 bytes
PROTOCOL_VERSION = 1
BROWSERS = frozenset({"chrome", "edge"})
FIELDS = frozenset({"v", "type", "browser", "instance", "seq", "ts", "focused", "domain"})
TITLE_FIELDS = FIELDS | {"title"}
SPECIAL_DOMAINS = frozenset({"localhost", "local-address"})

_HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")
_INSTANCE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class BrowserState:
    browser: str
    instance: str
    seq: int
    ts_ms: int
    focused: bool
    domain: str | None
    title: str | None = None


def read_message(stream: BinaryIO) -> dict | None:
    """Next message, or None when the browser closed the pipe."""
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise ProtocolError("truncated length prefix")
    (length,) = struct.unpack("<I", header)
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"message length {length} out of range")
    body = stream.read(length)
    if len(body) < length:
        raise ProtocolError("truncated message")
    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("not JSON") from exc
    if not isinstance(message, dict):
        raise ProtocolError("not an object")
    return message


def write_message(stream: BinaryIO, message: dict) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def valid_domain(domain: object) -> bool:
    return isinstance(domain, str) and (
        domain in SPECIAL_DOMAINS or bool(_HOSTNAME.match(domain))
    )


def parse_state(message: dict) -> BrowserState:
    """Validate a ``state`` message; raises ProtocolError with the first problem found."""
    if set(message) not in (FIELDS, TITLE_FIELDS):
        raise ProtocolError("unexpected or missing fields")
    if message["v"] != PROTOCOL_VERSION or message["type"] != "state":
        raise ProtocolError("unsupported version or type")
    if message["browser"] not in BROWSERS:
        raise ProtocolError("unknown browser")
    instance = message["instance"]
    if not isinstance(instance, str) or not _INSTANCE.match(instance):
        raise ProtocolError("bad instance id")
    seq, ts = message["seq"], message["ts"]
    for value in (seq, ts):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProtocolError("bad seq or ts")
    focused, domain = message["focused"], message["domain"]
    if not isinstance(focused, bool):
        raise ProtocolError("bad focused flag")
    if domain is not None and not valid_domain(domain):
        raise ProtocolError("bad domain")
    title = message.get("title")
    if title is not None:
        if (not isinstance(title, str) or not 0 < len(title) <= 160
                or any(ord(c) < 32 or ord(c) == 127 for c in title)
                or "://" in title or not focused or not domain):
            raise ProtocolError("invalid page title")
    return BrowserState(
        message["browser"], instance, seq, ts, focused, domain if focused else None, title
    )
