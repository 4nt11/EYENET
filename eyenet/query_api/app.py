"""FastAPI app factory for the read-only graph query API.

PLAN §5: localhost-only by default. No write endpoints.
Operator decisions are CLI-only and audit-logged.

Usage:
    from eyenet.query_api.app import create_app
    app = create_app(storage)
    uvicorn.run(app, host="127.0.0.1", port=8765)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository

from . import deps
from .routes import router


def create_app(storage: BaseRepository) -> FastAPI:
    """Build and return a read-only FastAPI app with storage injected."""

    app = FastAPI(
        title="EYENET Query API",
        version="0.1.0",
        description="Read-only graph query API. No write endpoints.",
        docs_url="/docs",
        redoc_url=None,
    )

    # Override the storage dependency for all routes.
    app.dependency_overrides[deps.get_storage] = lambda: storage

    app.include_router(router)

    return app


__all__ = ["create_app"]
