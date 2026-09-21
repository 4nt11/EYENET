# SPDX-License-Identifier: AGPL-3.0-or-later
"""X-Forwarded-For middleware (API_PLAN §12.4, M9.I2).

Off by default. When ``EYENET_API_TRUST_PROXY_HEADERS`` is truthy, rewrites the
ASGI scope's client address to the leftmost ``X-Forwarded-For`` hop so
downstream (the rate-limiter's IP fallback, audit) sees the real client rather
than the proxy. Untrusted deployments MUST NOT honour the header — it is
client-supplied and trivially spoofed — so the flag gates it and the middleware
is only added when trusted.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_TRUST_PROXY_ENV = "EYENET_API_TRUST_PROXY_HEADERS"
_TRUTHY = {"1", "true", "yes"}


def trust_proxy_headers() -> bool:
    return os.environ.get(_TRUST_PROXY_ENV, "").strip().lower() in _TRUTHY


class XForwardedForMiddleware:
    """Rewrite ``scope['client']`` from the leftmost XFF hop.

    Only wired in when :func:`trust_proxy_headers` is true, so no runtime flag
    check is needed here — presence in the stack means the operator opted in.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client_ip = _leftmost_xff(scope.get("headers", []))
            if client_ip is not None:
                # ponytail: trusts the leftmost XFF hop; real multi-hop proxy
                # chains need a trusted-hop count — add EYENET_API_TRUSTED_HOPS
                # if ever deployed behind >1 proxy.
                scope = dict(scope)
                scope["client"] = (client_ip, 0)
        await self.app(scope, receive, send)


def _leftmost_xff(headers: list[tuple[bytes, bytes]]) -> str | None:
    for name, value in headers:
        if name == b"x-forwarded-for":
            first = value.split(b",", 1)[0].strip()
            if first:
                return first.decode("latin-1")
    return None


__all__ = ["XForwardedForMiddleware", "trust_proxy_headers"]
