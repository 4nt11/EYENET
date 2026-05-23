"""`Membership` — Actor ↔ Group join (MODELS §2.2).

Lurkers join without speaking; admins are admins even when silent. This is
distinct signal from messaging.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import DbRowBase
from .enums import MembershipRole


class MembershipRow(DbRowBase):
    """Persisted Actor-Group membership row (MODELS §2.2)."""

    actor_id: UUID
    group_id: UUID
    role: MembershipRole = MembershipRole.UNKNOWN
    joined_at_source: datetime | None = None
    joined_at_ingest: datetime
    left_at_ingest: datetime | None = None


__all__ = ["MembershipRow"]
