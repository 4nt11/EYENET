"""Shared SQLModel base.

All EYENET tables share `SQLModel.metadata` for v0. Per PLAN §5.2 the
storage layer will physically split these across one SQLite file per concern;
that split is a routing decision in `eyenet.storage` (per-store engines
binding the same metadata classes), NOT a metadata-multiplexing trick at the
model layer. This keeps mappings simple and migrations linear.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import SQLModel
from uuid_extensions import uuid7


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def new_uuid7() -> UUID:
    return UUID(str(uuid7()))


__all__ = ["SQLModel", "new_uuid7", "now_utc"]
