# SPDX-License-Identifier: AGPL-3.0-or-later
"""Group I bring-up middleware (§12.4, M9.I1/I2) — CORS config, XFF, rate limit.

Pure-ASGI drives over hand-built scope/receive/send (mirrors
``test_idempotency_middleware.py``); no TestClient, no DB.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from eyenet.api.middleware import cors, rate_limit, xff

pytestmark = pytest.mark.unit

Scope = dict[str, Any]
Message = dict[str, Any]


# --- helpers -----------------------------------------------------------------


async def _drive(app: Any, scope: Scope) -> tuple[int, dict[bytes, bytes], bytes]:
    """Run an ASGI app once; return (status, headers, body)."""

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = dict(start.get("headers", []))
    return start["status"], headers, body


class _Inner:
    """Inner app that 200s and records the scope it was called with."""

    def __init__(self) -> None:
        self.seen_scope: Scope | None = None

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        self.seen_scope = scope
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _scope(
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] = ("1.2.3.4", 0),
) -> Scope:
    return {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": headers or [],
        "client": client,
    }


# --- CORS origin config ------------------------------------------------------


def test_cors_origins_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_API_CORS_ORIGINS", raising=False)
    assert cors.cors_origins() == []


def test_cors_origins_comma_split_and_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_API_CORS_ORIGINS", " https://a.io , https://b.io ,")
    assert cors.cors_origins() == ["https://a.io", "https://b.io"]


# --- X-Forwarded-For ---------------------------------------------------------


async def test_xff_rewrites_client_from_leftmost_hop() -> None:
    inner = _Inner()
    mw = xff.XForwardedForMiddleware(inner)
    scope = _scope(headers=[(b"x-forwarded-for", b"9.9.9.9, 10.0.0.1")], client=("127.0.0.1", 0))
    await _drive(mw, scope)
    assert inner.seen_scope is not None
    assert inner.seen_scope["client"] == ("9.9.9.9", 0)


async def test_xff_noop_without_header() -> None:
    inner = _Inner()
    mw = xff.XForwardedForMiddleware(inner)
    scope = _scope(client=("127.0.0.1", 0))
    await _drive(mw, scope)
    assert inner.seen_scope is not None
    assert inner.seen_scope["client"] == ("127.0.0.1", 0)


def test_trust_proxy_headers_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EYENET_API_TRUST_PROXY_HEADERS", "yes")
    assert xff.trust_proxy_headers() is True
    monkeypatch.setenv("EYENET_API_TRUST_PROXY_HEADERS", "0")
    assert xff.trust_proxy_headers() is False


# --- rate limit --------------------------------------------------------------


class _Clock:
    """Injectable monotonic-clock stand-in with manual advance."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def test_rate_limit_admits_then_429() -> None:
    mw = rate_limit.RateLimitMiddleware(_Inner(), limit=2, window=60.0, clock=_Clock())
    hdrs = [(b"authorization", b"Bearer tok-abc")]

    s1, h1, _ = await _drive(mw, _scope(headers=hdrs))
    s2, h2, _ = await _drive(mw, _scope(headers=hdrs))
    s3, h3, body = await _drive(mw, _scope(headers=hdrs))

    assert (s1, s2, s3) == (200, 200, 429)
    assert h1[b"x-ratelimit-remaining"] == b"1"
    assert h2[b"x-ratelimit-remaining"] == b"0"
    assert h3[b"x-ratelimit-remaining"] == b"0"
    assert b"retry-after" in h3
    problem = json.loads(body)
    assert problem["status"] == 429


async def test_rate_limit_window_slides() -> None:
    clock = _Clock()
    mw = rate_limit.RateLimitMiddleware(_Inner(), limit=1, window=60.0, clock=clock)
    hdrs = [(b"authorization", b"Bearer tok-xyz")]

    s1, _, _ = await _drive(mw, _scope(headers=hdrs))
    s2, _, _ = await _drive(mw, _scope(headers=hdrs))
    clock.t += 61.0  # advance past the window; the old timestamp evicts
    s3, _, _ = await _drive(mw, _scope(headers=hdrs))

    assert (s1, s2, s3) == (200, 429, 200)


async def test_rate_limit_keys_per_token() -> None:
    mw = rate_limit.RateLimitMiddleware(_Inner(), limit=1, window=60.0, clock=_Clock())

    a1, _, _ = await _drive(mw, _scope(headers=[(b"authorization", b"Bearer AAA")]))
    b1, _, _ = await _drive(mw, _scope(headers=[(b"authorization", b"Bearer BBB")]))
    a2, _, _ = await _drive(mw, _scope(headers=[(b"authorization", b"Bearer AAA")]))

    # Distinct tokens get independent buckets; the third (token AAA again) is over.
    assert (a1, b1, a2) == (200, 200, 429)


def test_rate_limit_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EYENET_API_RATE_LIMIT", raising=False)
    monkeypatch.delenv("EYENET_API_RATE_WINDOW_SECONDS", raising=False)
    limit, window = rate_limit.rate_limit_config()
    assert limit > 0
    assert window > 0
