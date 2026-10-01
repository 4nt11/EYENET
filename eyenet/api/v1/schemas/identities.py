"""Identity-pool action bodies + global panic body.

Every write returns `WriteAccepted` (see `writes.py`); only the input
bodies live here.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — IdentityActionRequest, PanicRequest.
API_PLAN §3.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import IdentityRole, IdentityState
from eyenet.contracts.identity import IdentityRow

from ._base import ApiSchema
from .pagination import CursorPage


class IdentitySummary(ApiSchema):
    """List view of a pool identity (GET /v1/identities).

    OPSEC fields are intentionally omitted: ``session_path`` (filesystem path
    to the encrypted session blob) and ``proxy_uri`` (may embed credentials)
    never cross the read surface.
    """

    identity_id: UUID
    name: str
    source_id: UUID
    role: IdentityRole
    state: IdentityState
    last_used_at: datetime | None = None

    @classmethod
    def from_domain(cls, row: IdentityRow) -> IdentitySummary:
        return cls(
            identity_id=row.id,
            name=row.name,
            source_id=row.source_id,
            role=row.role,
            state=row.state,
            last_used_at=row.last_used_at,
        )


class IdentityDetail(IdentitySummary):
    """Detail view (GET /v1/identities/{id}) — same OPSEC omissions.

    Surfaces the forum collector's PACING profile so the operator can see what an
    identity's collector is actually running: the named evasion level (if one was
    chosen) and the resolved inter-request delay window. Non-secret config, read
    from ``source_config``; ``None`` for non-forum identities.
    """

    cooldown_seconds: int
    graduated_at: datetime | None = None
    notes: str | None = None
    forum_evasion_level: str | None = None
    forum_delay_min: float | None = None
    forum_delay_max: float | None = None

    @classmethod
    def from_domain(cls, row: IdentityRow) -> IdentityDetail:
        cfg = row.source_config or {}
        return cls(
            identity_id=row.id,
            name=row.name,
            source_id=row.source_id,
            role=row.role,
            state=row.state,
            last_used_at=row.last_used_at,
            cooldown_seconds=row.cooldown_seconds,
            graduated_at=row.graduated_at,
            notes=row.notes,
            forum_evasion_level=cfg.get("forum_evasion_level"),
            forum_delay_min=cfg.get("forum_delay_min"),
            forum_delay_max=cfg.get("forum_delay_max"),
        )


class CursorPageIdentitySummary(CursorPage[IdentitySummary]):
    """200 page response for GET /v1/identities."""


class IdentityActionRequest(ApiSchema):
    """Body for `POST /v1/identities/{id}/{claim,release}` and `/freeze_all`."""

    reason: str = Field(min_length=1, max_length=1024)
    note: str | None = Field(default=None, max_length=4096)


class PanicRequest(ApiSchema):
    """Body for `POST /v1/panic` — global system halt.

    `confirm` is a mandatory blocking acknowledgment. The literal string
    `I_UNDERSTAND` must be present to prevent accidental panic from a
    stray curl.
    """

    reason: str = Field(min_length=1, max_length=1024)
    confirm: Literal["I_UNDERSTAND"]


__all__ = [
    "CursorPageIdentitySummary",
    "IdentityActionRequest",
    "IdentityDetail",
    "IdentitySummary",
    "PanicRequest",
]
