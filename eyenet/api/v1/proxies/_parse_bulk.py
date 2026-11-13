# SPDX-License-Identifier: AGPL-3.0-or-later
"""Line parser for the bulk import endpoint.

The operator pastes a textarea where each line is one proxy. We accept the
common serialization shapes (see docstring on :class:`ProxyBulkCreateRequest`)
and emit a list of :class:`ParsedEntry` + a list of rejection messages the
handler surfaces back.

Deliberately NOT using ``urllib.parse.urlparse`` for everything: the
``host:port:user:pass`` form is a proxy-tool convention, not a URL, and
urlparse mis-handles it. The ``scheme://`` shapes do go through urlparse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple
from urllib.parse import urlparse

from eyenet.contracts.enums import ProxyKind

_SCHEME_TO_KIND: dict[str, ProxyKind] = {
    "socks5": ProxyKind.SOCKS5,
    "socks5h": ProxyKind.SOCKS5,   # DNS-via-proxy variant; same wire kind.
    "http": ProxyKind.HTTP,
    "https": ProxyKind.HTTPS,
    "mtproto": ProxyKind.MTPROXY,
    "mtproxy": ProxyKind.MTPROXY,
}


class ParsedEntry(NamedTuple):
    kind: ProxyKind
    host: str
    port: int
    secret: str | None  # plaintext credential (handler encrypts before DB)


@dataclass
class BulkParseResult:
    entries: list[ParsedEntry]
    rejected: list[str]  # "line N: <reason>: <offending line>"


def parse_bulk_lines(
    lines: list[str],
    *,
    default_kind: ProxyKind | None,
) -> BulkParseResult:
    entries: list[ParsedEntry] = []
    rejected: list[str] = []
    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = _parse_one(line, default_kind=default_kind)
        except ValueError as exc:
            rejected.append(f"line {idx}: {exc}: {line}")
            continue
        entries.append(entry)
    return BulkParseResult(entries=entries, rejected=rejected)


def _parse_one(line: str, *, default_kind: ProxyKind | None) -> ParsedEntry:
    # Scheme-prefixed forms.
    if "://" in line:
        parsed = urlparse(line)
        scheme = (parsed.scheme or "").lower()
        if scheme not in _SCHEME_TO_KIND:
            raise ValueError(f"unknown scheme {scheme!r}")
        kind = _SCHEME_TO_KIND[scheme]
        host = parsed.hostname or ""
        port = parsed.port
        if not host or not port:
            raise ValueError("missing host or port")
        secret: str | None
        if kind == ProxyKind.MTPROXY:
            # mtproto://host:port?secret=HEX
            qs = dict(
                pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair
            )
            secret = qs.get("secret")
            if not secret:
                raise ValueError("mtproto requires ?secret=HEX")
        elif parsed.username:
            # SOCKS5 / HTTP with user:pass
            user = parsed.username
            pw = parsed.password or ""
            secret = f"{user}:{pw}"
        else:
            secret = None
        return ParsedEntry(kind=kind, host=host, port=port, secret=secret)

    # host:port:user:pass or host:port
    parts = line.split(":")
    if len(parts) not in (2, 4):
        raise ValueError("expected host:port or host:port:user:pass")
    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"bad port {parts[1]!r}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"port out of range: {port}")
    secret = f"{parts[2]}:{parts[3]}" if len(parts) == 4 else None
    kind = default_kind or ProxyKind.SOCKS5
    return ParsedEntry(kind=kind, host=host, port=port, secret=secret)


__all__ = ["BulkParseResult", "ParsedEntry", "parse_bulk_lines"]
