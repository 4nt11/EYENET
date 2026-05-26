"""GroupAccessArtifact contract (MODELS §2.24, M9.C6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import ArtifactSubjectKind, ArtifactValidationState, GroupAccessKind


class GroupAccessArtifactRow(DbRowBase):
    """Persisted GroupAccessArtifact row (MODELS §2.24).

    Subject is exactly one of (group_id, candidate_id) — discriminated by
    ``subject_kind``. ``value`` is the transferable identifier (``@handle``,
    ``t.me/+abc``, ``#room:server``, ``chat.whatsapp.com/X``, etc.) and is
    null for kinds that carry no token (``direct_invite``, ``access_blocked``).
    """

    subject_kind: ArtifactSubjectKind
    group_id: UUID | None = None
    candidate_id: UUID | None = None
    kind: GroupAccessKind
    value: str | None = Field(default=None, max_length=1024)
    details: dict[str, Any] = Field(default_factory=dict)
    discovered_via_mention_id: UUID | None = None
    discovered_at_ingest: datetime
    last_validated_at: datetime | None = None
    validation_state: ArtifactValidationState = ArtifactValidationState.UNVERIFIED
    requires_admin_approval: bool = False
    expires_at: datetime | None = None


__all__ = ["GroupAccessArtifactRow"]
