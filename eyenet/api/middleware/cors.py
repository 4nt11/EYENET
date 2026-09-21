# SPDX-License-Identifier: AGPL-3.0-or-later
"""CORS origin config for the operator UI (API_PLAN §12.4, M9.I2).

The operator frontend is a *separate origin*; without CORS a browser cannot call
the API at all. Origins are configured via ``EYENET_API_CORS_ORIGINS`` (comma-
separated) — env, not ``config.toml``, mirroring every other ``EYENET_API_*``
knob. Empty default → no CORS middleware is added (secure default; never ``*``).

The middleware itself is starlette's ``CORSMiddleware`` (shipped with FastAPI);
this module only resolves the configured origin list. Wiring lives in
``create_app``.
"""

from __future__ import annotations

import os

_CORS_ORIGINS_ENV = "EYENET_API_CORS_ORIGINS"


def cors_origins() -> list[str]:
    """Configured operator-UI origins, or ``[]`` when unset (CORS disabled)."""
    raw = os.environ.get(_CORS_ORIGINS_ENV, "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


__all__ = ["cors_origins"]
