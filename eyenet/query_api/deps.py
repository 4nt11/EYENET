"""Dependency providers for the query API.

`get_storage` is the canonical dependency. In production, `create_app`
overrides it to return the real BaseRepository. In tests, TestClient
overrides it to return a seeded in-memory storage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository


def get_storage() -> BaseRepository:  # pragma: no cover
    raise RuntimeError("storage dependency not configured — call create_app(storage) first")


__all__ = ["get_storage"]
