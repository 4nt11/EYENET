"""External-witness anchor records — API_PLAN §5.9.

Every 5 minutes the deployment emits a signed `(audit_head, journal_head)`
record on the bus subject `eyenet.audit.anchor` and to operator-configured
sinks (file, webhook, email). The same records are queryable via
`GET /v1/audit/anchors` for the operator's own audit.

Wire-shape mirror of `Anchor` / `CursorPageAnchor` in
`contracts/openapi/eyenet.v1.yaml`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema

if TYPE_CHECKING:
    from eyenet.contracts.anchor import AnchorRow

_HEX_64 = r"^[0-9a-f]{64}$"
_ED25519_SIG = r"^ed25519:[A-Za-z0-9_\-]{86,90}={0,2}$"


class Anchor(ApiSchema):
    """One anchor record — the external-witness primitive."""

    deployment_id: UUID
    anchor_seq: int = Field(ge=0, description="Monotonic per-deployment counter.")
    anchored_at: datetime
    audit_head: str = Field(
        pattern=_HEX_64,
        description="`self_hash` of the latest `audit_log_event` at anchor time.",
    )
    journal_head: str = Field(
        pattern=_HEX_64,
        description="`self_hash` of the latest `file_access_journal` row at anchor time.",
    )
    signature: str = Field(
        pattern=_ED25519_SIG,
        description="Ed25519 server signature over the canonical anchor form.",
    )

    @classmethod
    def from_domain(cls, row: AnchorRow) -> Anchor:
        return cls(
            deployment_id=row.deployment_id,
            anchor_seq=row.anchor_seq,
            anchored_at=row.anchored_at,
            audit_head=row.audit_head,
            journal_head=row.journal_head,
            signature=row.signature,
        )


class CursorPageAnchor(ApiSchema):
    """Paged anchor records (newest first)."""

    items: list[Anchor] = Field(default_factory=list)
    next_cursor: str | None = None
    estimated_total: int | None = Field(default=None, ge=0)


__all__ = ["Anchor", "CursorPageAnchor"]
