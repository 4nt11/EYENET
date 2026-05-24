"""Reclassification surfaces — API_PLAN §4.9.

Promotion-only sensitivity-tier updates for observations and attachments.
Monotone enforcement happens at three layers (endpoint, storage CHECK, audit);
these schemas are the wire shape for layer one.

`operator_signature` is the same Ed25519 signature format as §5.6
(`ed25519:<urlsafe-base64>`). Without a signed body the endpoint fails closed
with 403 — a session JWT alone never authorises reclassification.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import ReclassificationSubjectKind, SensitivityTier

_ED25519_SIG = r"^ed25519:[A-Za-z0-9_\-]{86,90}={0,2}$"


class ReclassificationRequest(ApiSchema):
    """Body for POST /v1/{observations,attachments}/{id}/reclassify.

    Server validates `new_tier > effective_tier(row)` before accepting; the
    storage CHECK constraint is the second line of defence, and the audit row
    records both prior and new tier as the third.
    """

    new_tier: SensitivityTier = Field(
        description=(
            "Target tier. Server rejects `normal` and any value not strictly "
            "higher than the row's current effective tier."
        ),
    )
    reason: str = Field(
        min_length=32,
        max_length=1024,
        description="Case identifier, triggering observation, peer-review reference.",
    )
    viewing_context: str | None = Field(
        default=None,
        max_length=1024,
        description="What the operator was doing when they made the call.",
    )
    operator_signature: str = Field(
        pattern=_ED25519_SIG,
        description="Ed25519 signature over the EYENET-SIG-v1 canonical form (§5.7).",
    )
    case_refs: list[UUID] = Field(
        default_factory=list,
        max_length=32,
        description="Cases where this row is evidence (§4.10.7). Server validates each exists.",
    )


class ReclassificationResult(ApiSchema):
    """200 envelope returned by both reclassify endpoints.

    Records the post-write state of the row's sensitivity columns and the
    audit event that anchors the change. Replay invariant (§4.9): given the
    audit log alone, the effective tier at every point in time is
    reconstructable.
    """

    subject_id: UUID
    subject_kind: ReclassificationSubjectKind
    classifier_tier: SensitivityTier = Field(
        description="The classifier's verdict at ingest — immutable, lower bound for all time.",
    )
    operator_tier_override: SensitivityTier = Field(
        description="The promoted tier just written. Always `>=` classifier_tier.",
    )
    effective_tier: SensitivityTier = Field(
        description="max(classifier_tier, operator_tier_override). The gate-deciding value.",
    )
    prior_effective_tier: SensitivityTier = Field(
        description="effective_tier before this call — for audit reconciliation.",
    )
    audit_event_id: UUID = Field(description="FK → audit_log_event.id for this reclassification.")
    reclassified_at: datetime
    grant_id: UUID = Field(description="The `admin:reclassify` grant that authorised this call.")


__all__ = [
    "ReclassificationRequest",
    "ReclassificationResult",
]
