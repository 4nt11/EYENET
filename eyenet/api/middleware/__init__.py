# SPDX-License-Identifier: AGPL-3.0-or-later
"""ASGI middleware for the EYENET v1 API."""

from eyenet.api.middleware.cors import cors_origins
from eyenet.api.middleware.evidence_access import evidence_access_dispatch
from eyenet.api.middleware.idempotency import IdempotencyMiddleware
from eyenet.api.middleware.rate_limit import RateLimitMiddleware, rate_limit_config
from eyenet.api.middleware.xff import XForwardedForMiddleware, trust_proxy_headers

__all__ = [
    "IdempotencyMiddleware",
    "RateLimitMiddleware",
    "XForwardedForMiddleware",
    "cors_origins",
    "evidence_access_dispatch",
    "rate_limit_config",
    "trust_proxy_headers",
]
