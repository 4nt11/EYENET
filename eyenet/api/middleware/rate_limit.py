# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-token sliding-window rate limit (API_PLAN §12.4, M9.I1).

A **pure ASGI** middleware. Keyed per credential: ``sha256(bearer)[:16]`` when an
``Authorization: Bearer`` header is present, else the client IP (post-XFF). No
JWT/PAT decode is needed — the raw credential string is already a stable
per-token key, and distinct tokens hash to distinct buckets, so this yields true
per-token isolation without waiting for FastAPI dependency resolution (auth runs
as a dependency, i.e. *after* all middleware).

Sliding window: a deque of ``time.monotonic()`` timestamps per key. ``monotonic``
(not wall clock) is used so an NTP step or clock skew cannot widen or shift a
window. When the window is full the request is refused with a 429 ProblemDetail
carrying ``Retry-After`` and ``X-RateLimit-Remaining: 0``; otherwise the
remaining count is exposed on the response.

ponytail: per-process in-memory window; single API instance (small-operator
default cardinality 1). Horizontal scale → shared store (Redis).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from typing import TYPE_CHECKING
from uuid import uuid4

from eyenet.api.v1.schemas.errors import ProblemDetail

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LIMIT_ENV = "EYENET_API_RATE_LIMIT"
_WINDOW_ENV = "EYENET_API_RATE_WINDOW_SECONDS"
_DEFAULT_LIMIT = 300
_DEFAULT_WINDOW = 60.0
_PROBLEM_JSON = "application/problem+json"
_BEARER_PREFIX = b"bearer "


def rate_limit_config() -> tuple[int, float]:
    """``(limit, window_seconds)`` from env; ``limit <= 0`` disables the middleware."""
    limit = int(os.environ.get(_LIMIT_ENV, _DEFAULT_LIMIT))
    window = float(os.environ.get(_WINDOW_ENV, _DEFAULT_WINDOW))
    return limit, window


class RateLimitMiddleware:
    """Sliding-window per-credential limiter. See module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.limit = limit
        self.window = window
        self._clock = clock
        self._buckets: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        remaining = await self._admit(_key(scope))
        if remaining is None:
            await _send_429(send, _path(scope), self.window)
            return
        await self.app(scope, receive, _remaining_send(send, remaining))

    async def _admit(self, key: str) -> int | None:
        """Admit and return remaining quota, or ``None`` when the window is full."""
        now = self._clock()
        cutoff = now - self.window
        async with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return None
            bucket.append(now)
            return self.limit - len(bucket)


def _key(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"authorization" and value[:7].lower() == _BEARER_PREFIX:
            token = value[7:].strip()
            if token:
                return "t:" + hashlib.sha256(token).hexdigest()[:16]
    client = scope.get("client")
    ip = client[0] if client else "unknown"
    return "ip:" + str(ip)


def _path(scope: Scope) -> str:
    path = scope.get("path")
    return path if isinstance(path, str) else "/"


def _remaining_send(send: Send, remaining: int) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
            message = {**message, "headers": headers}
        await send(message)

    return wrapped


async def _send_429(send: Send, path: str, window: float) -> None:
    problem = ProblemDetail(
        type="about:blank",
        title="Too Many Requests",
        status=429,
        detail="rate limit exceeded; retry after the window resets",
        instance=path,
        request_id=uuid4().hex,
    )
    data = json.dumps(problem.model_dump(mode="json", exclude_none=True)).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", _PROBLEM_JSON.encode()),
                (b"content-length", str(len(data)).encode()),
                (b"retry-after", str(int(window)).encode()),
                (b"x-ratelimit-remaining", b"0"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": data, "more_body": False})


__all__ = ["RateLimitMiddleware", "rate_limit_config"]
