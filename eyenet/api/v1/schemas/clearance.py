"""Clearance grants — API_PLAN §4.8.

Schemas mirror `contracts/openapi/eyenet.v1.yaml`:

- `ClearanceGrantRequest` — POST body to create a grant. Caller must hold
  `admin:clearance`. `expires_at` is mandatory; server enforces ≤ 90 days
  from `granted_at`.
- `ClearanceGrantSummary` / `ClearanceGrantDetail` — read shapes. Detail adds
  the justification text and the full revocation/parent-chain fields.
- `ClearanceRevokeRequest` — POST body for `/revoke`.

`from_domain()` deferred to M9.1 storage work — the
`system_user_clearance_grant` table doesn't exist yet.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import ClearanceScope


class ClearanceGrantRequest(ApiSchema):
    """Body for `POST /v1/clearance/grants`."""

    user_id: UUID
    scope: ClearanceScope
    reason: str = Field(
        min_length=16,
        max_length=1024,
        description="Case identifier, incident ID, peer-review reference. 'ok' is not a reason.",
    )
    expires_at: datetime = Field(description="Server caps at granted_at + 90 days (§4.8).")
    case_refs: list[UUID] = Field(
        default_factory=list,
        max_length=32,
        description="Cases this grant authorises work under (§4.10.7).",
    )


class ClearanceRevokeRequest(ApiSchema):
    """Body for `POST /v1/clearance/grants/{grant_id}/revoke`."""

    revocation_reason: str = Field(min_length=1, max_length=1024)


class ClearanceGrantSummary(ApiSchema):
    """List-row shape for clearance grants."""

    grant_id: UUID
    user_id: UUID
    scope: ClearanceScope
    granted_by_user_id: UUID
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    active: bool = Field(description="Server-evaluated ACTIVE(now) predicate from §4.8.")


class ClearanceGrantDetail(ClearanceGrantSummary):
    """Full grant detail incl. justification and revocation/parent chain."""

    reason: str = Field(min_length=16, max_length=1024)
    revoked_by_user_id: UUID | None = None
    revocation_reason: str | None = Field(default=None, max_length=1024)
    parent_grant_id: UUID | None = Field(
        default=None,
        description="If this row is a renewal, the prior `grant_id` it succeeds.",
    )


class CursorPageClearanceGrantSummary(ApiSchema):
    """Paged grant summaries."""

    items: list[ClearanceGrantSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


__all__ = [
    "ClearanceGrantDetail",
    "ClearanceGrantRequest",
    "ClearanceGrantSummary",
    "ClearanceRevokeRequest",
    "CursorPageClearanceGrantSummary",
]
