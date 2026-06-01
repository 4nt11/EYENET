"""`Source` contract — a specific platform origin (MODELS §1.1).

Telegram has one Source row; each forum domain is its own Source row.
NEVER carries credentials — those live on `Identity` (MODELS §2.1).

Surface: db (no SUBJECT exported).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import DbRowBase
from .enums import SourceKind


class SourceRow(DbRowBase):
    """Persisted Source row (MODELS §1.1).

    ``canonical_url`` is display-only — when set, the host portion must
    match the Source's primary :class:`SourceDomainRow` pattern. The
    storage layer enforces this via ``set_source_canonical_url`` (M9.C2).
    """

    kind: SourceKind
    display_name: str
    canonical_url: str | None = None
    created_at: datetime
    notes: str | None = None


class SourceBridgeSummary(BaseModel):
    """Bridge-resolution counts for ``GET /v1/sources/{id}/bridge-summary``.

    Grounded in the actual ``InfrastructureArtifact`` schema (MODELS §2.7,
    §2.25): only ``RESOLVED`` artifacts carry a ``resolved_to_source_id``
    (enforced by ``ck_artifact_resolved_fk_paired``), so ``resolved`` is the
    only genuinely per-source count. ``unresolved`` / ``ambiguous`` /
    ``not_applicable`` are NOT linked to any Source — they're surfaced as
    system-wide "outstanding bridge work" context for the operator viewing
    this Source. The §3.8 ``pending_source`` bucket has no backing
    ``ResolutionState`` value and is intentionally omitted.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    resolved: int = Field(ge=0, description="Artifacts resolved_to_source_id == this source.")
    unresolved: int = Field(
        ge=0, description="System-wide UNRESOLVED artifacts (not source-linked)."
    )
    ambiguous: int = Field(ge=0, description="System-wide AMBIGUOUS artifacts (not source-linked).")
    not_applicable: int = Field(
        ge=0, description="System-wide NOT_APPLICABLE artifacts (not source-linked)."
    )


__all__ = ["SourceBridgeSummary", "SourceRow"]
