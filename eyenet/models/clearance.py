"""SystemUserClearanceGrantTable — see contracts/clearance.py (API_PLAN §4.8).

Lives in `audit.db`. Cross-store reference to `system_user` (no FK).

CHECK constraints (ANSI SQL only — dialect-agnostic):
- revocation ordering: `revoked_at IS NULL OR revoked_at >= granted_at`
- reason length: ≥16 chars (mandatory justification)
- revocation triplet nullability symmetry

The 90-day expiry cap is enforced at the **storage-helper layer**, not in
schema. Date math (`julianday`/`INTERVAL '90 days'`/`DATEDIFF`) has no
portable ANSI form across SQLite, Postgres, MySQL — keeping the model layer
dialect-agnostic costs us one defense-in-depth check at the SQL boundary,
which the helper enforces before INSERT instead.

Cache-bypass note (§4.4.1): clearance resolution joins the no-cache list.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import ClearanceScope

from ._base import new_uuid7


class SystemUserClearanceGrantTable(SQLModel, table=True):
    """Persisted clearance grant (API_PLAN §4.8)."""

    __tablename__ = "system_user_clearance_grant"
    __table_args__ = (
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="ck_clearance_grant_revoke_after_grant",
        ),
        CheckConstraint("length(reason) >= 16", name="ck_clearance_grant_reason_min"),
        CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_user_id IS NULL AND revocation_reason IS NULL) "
            "OR (revoked_at IS NOT NULL AND revoked_by_user_id IS NOT NULL "
            "AND revocation_reason IS NOT NULL)",
            name="ck_clearance_grant_revoke_triplet",
        ),
        # Hot path for the active-grant resolver: filter by user+scope, range-scan expiry.
        Index("ix_clearance_active", "user_id", "scope", "expires_at"),
        # Admin audit view: "what did granter X authorise, when?"
        Index("ix_clearance_by_granter", "granted_by_user_id", "granted_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    user_id: UUID = Field(index=True)
    scope: ClearanceScope
    granted_by_user_id: UUID
    reason: str = Field(max_length=1024)
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)
    parent_grant_id: UUID | None = Field(default=None)


__all__ = ["SystemUserClearanceGrantTable"]
