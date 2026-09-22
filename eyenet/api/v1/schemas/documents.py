# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wire schemas for the document upload + retrieval surface (M10 slice 7 + viewer)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import SensitivityTier

from ._base import ApiSchema
from .pagination import CursorPage

if TYPE_CHECKING:
    from eyenet.contracts.document import DocumentRow

_HEX_64 = r"^[0-9a-f]{64}$"


class DocumentSummary(ApiSchema):
    """Projection of a DocumentRow for the triage list (``GET /v1/documents``).

    Metadata only — no ``extracted_text`` and no ``classification`` (those are
    detail-surface concerns served by the clearance-gated manifest). ``tier`` is
    the effective sensitivity (``operator_tier_override`` over ``classifier_tier``);
    ``classifier_tier`` is surfaced too so the UI can show a promotion badge.
    """

    document_id: UUID
    sha256: str = Field(pattern=_HEX_64, description="SHA-256 of the stored bytes, hex.")
    mime: str = Field(max_length=128)
    size_bytes: int = Field(ge=0)
    doc_kind: str | None = None
    filename: str | None = None
    review_required: bool
    classifier_tier: SensitivityTier
    tier: SensitivityTier = Field(description="Effective tier = override or classifier.")
    uploaded_at: datetime
    ingested_at: datetime

    @classmethod
    def from_domain(cls, row: DocumentRow) -> DocumentSummary:
        return cls(
            document_id=row.id,
            sha256=row.sha256,
            mime=row.mime,
            size_bytes=row.size_bytes,
            doc_kind=row.doc_kind,
            filename=row.filename,
            review_required=row.review_required,
            classifier_tier=row.classifier_tier,
            tier=row.operator_tier_override or row.classifier_tier,
            uploaded_at=row.uploaded_at,
            ingested_at=row.ingested_at,
        )


class DocumentUploadResult(ApiSchema):
    """Result of ingesting one uploaded document — the settled classification.

    ``tier`` is the BINDING classifier tier (the deterministic ``MAX``; never
    lowered by the advisory LLM). ``review_required`` is True when the verdict
    carried any operator-review flag (LLM-higher-tier, counter-signal, or
    LLM-unavailable) — the document is classified, but an operator should look.
    """

    document_id: UUID
    tier: SensitivityTier
    sha256: str
    review_required: bool


class DocumentManifest(ApiSchema):
    """Metadata + provenance envelope: step 1 of the document access flow.

    Clearance-gated (a caller who cannot read the effective tier gets 403 before
    any of this leaks). Carries no bytes; the viewer uses ``classification`` +
    ``tier`` + ``review_required`` to render provenance, and ``access_nonce`` to
    fetch the raw bytes via the signed POST /access step. Calling the manifest
    appends NO file-access-journal row: it is not an access.

    ``classification`` is the already-redacted classification record persisted on
    the row (masked spans, no raw evidence text) so returning it leaks no content.
    """

    document_id: UUID
    content_hash: str = Field(pattern=_HEX_64, description="SHA-256 of the stored bytes, hex.")
    content_size: int = Field(ge=0)
    content_mime: str = Field(max_length=128)
    tier: SensitivityTier
    filename: str | None = None
    doc_kind: str | None = None
    review_required: bool
    classification: dict[str, Any] = Field(
        default_factory=dict,
        description="Redacted classification record (provenance/flags/versions; no raw spans).",
    )
    uploaded_at: datetime
    ingested_at: datetime
    access_nonce: UUID = Field(description="Single-use, 60s TTL, required for the /access step.")
    nonce_expires_at: datetime


class CursorPageDocumentSummary(CursorPage[DocumentSummary]):
    """200 page response for ``GET /v1/documents``."""


__all__ = [
    "CursorPageDocumentSummary",
    "DocumentManifest",
    "DocumentSummary",
    "DocumentUploadResult",
]
