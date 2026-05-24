"""`SystemUserClearanceGrant` — sensitive-evidence clearance (API_PLAN §4.8).

Court-defensible artifact: every grant carries a mandatory reason, a bounded
expiry (≤90 days), a granting officer, and a revocation history. Grant rows
are NEVER mutated after creation — revocation writes `revoked_at` /
`revoked_by_user_id` / `revocation_reason` on the same row but never edits
the original grant fields.

Scopes flowing through this lifecycle are listed in `ClearanceScope` — they
are NEVER present in any role baseline (see API_PLAN §4.6 ROLE_BASELINE).

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import ClearanceScope


class SystemUserClearanceGrantRow(DbRowBase):
    """Persisted clearance grant (API_PLAN §4.8).

    The `id` field is the grant_id wire identifier.

    Active predicate (resolver-side, not enforced in storage):
        granted_at <= now AND expires_at > now AND revoked_at IS NULL.

    Storage enforces the 90-day cap via CHECK; the resolver enforces the
    active predicate per request (cache bypass — §4.4.1).
    """

    user_id: UUID
    scope: ClearanceScope
    granted_by_user_id: UUID
    reason: str = Field(min_length=16, max_length=1024)
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)
    parent_grant_id: UUID | None = Field(
        default=None,
        description="Predecessor grant when this row supersedes an earlier "
        "grant (e.g. renewal). Not used for revocation chains — revocation "
        "mutates the original grant row.",
    )


__all__ = ["SystemUserClearanceGrantRow"]
