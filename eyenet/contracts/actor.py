"""`Actor` contract — observed person/entity (MODELS §1.2, §2.10).

`actor_key` is the opaque join key used in trace/log/bus contexts.
PLAN §0 / MODELS §0: `actor_key = "actor:" + sha256(source_kind || platform_userid)`.

Surface: db (Actor, ActorAliasHistory) — no SUBJECT.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import ActorAliasKind, SourceKind


def actor_key(source_kind: SourceKind | str, platform_userid: str) -> str:
    """Compute the canonical opaque actor join key.

    Stable across DB resets; identical on every operator workstation for the
    same (source_kind, platform_userid). PLAN §0 / MODELS §0.
    """

    kind = source_kind.value if isinstance(source_kind, SourceKind) else source_kind
    digest = hashlib.sha256(f"{kind}{platform_userid}".encode()).hexdigest()
    return f"actor:{digest}"


class ActorRow(DbRowBase):
    """Persisted Actor row (MODELS §1.2)."""

    actor_key: str = Field(description="opaque join key, see actor_key()")
    source_id: UUID
    platform_userid: str
    current_handle: str | None = None
    current_display_name: str | None = None
    first_seen_at_source: datetime | None = None
    first_seen_at_ingest: datetime
    last_seen_at_source: datetime | None = None
    last_seen_at_ingest: datetime
    is_bot_self_declared: bool = False
    notes: str | None = None
    operator_assessment: str | None = None


class ActorAliasHistoryRow(DbRowBase):
    """Append-only alias history (MODELS §2.10).

    `observed_until=None` means "still current".
    """

    actor_id: UUID
    kind: ActorAliasKind
    value: str
    observed_from: datetime
    observed_until: datetime | None = None


__all__ = ["ActorAliasHistoryRow", "ActorRow", "actor_key"]
