"""DocumentTable — see contracts/document.py.

A `Document` is a standalone uploaded artifact (operator drops a file in via
the API or CLI), as opposed to an `Attachment` which hangs off a collected
`MessageTable` row. It carries the SAME sensitivity columns as Attachment /
Observation so reclassification works uniformly (API_PLAN §4.7 / §4.9).

Forensic columns (M10 slice 7):
- `sha256`: content hash of the RAW uploaded bytes, computed HOST-SIDE at
  ingest — never over jail output, never over extracted text (which varies by
  extractor version). Mirrors `AttachmentTable.sha256`; indexed for dedup.
- `embedded_meta`: document-claimed metadata (PDF Info/XMP, DOCX core props,
  image EXIF, …). Attacker-controlled → captured verbatim as evidence but
  SANITIZED host-side before it lands here (stored-XSS vector).
- `classification`: the redacted classification record (provenance / flags /
  versions, no raw spans) — the court-quotable "why this tier".
- `extracted_text`: the full extracted body, retained as operator-grade
  evidence and gated by the row's effective tier.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Index
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import SensitivityTier

from ._base import new_uuid7
from .observation import TIER_MONOTONE_CK


class DocumentTable(SQLModel, table=True):
    __tablename__ = "document"
    __table_args__ = (
        Index(
            "ix_document_tier",
            "classifier_tier",
            "operator_tier_override",
        ),
        CheckConstraint(TIER_MONOTONE_CK, name="ck_document_tier_monotone"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    sha256: str = Field(index=True)
    mime: str
    size_bytes: int
    doc_kind: str | None = None
    filename: str | None = None
    storage_uri: str | None = None
    extracted_text: str | None = None
    embedded_meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    classification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    review_required: bool = False
    uploaded_by_user_id: UUID | None = None
    uploaded_at: datetime
    ingested_at: datetime
    classifier_tier: SensitivityTier = Field(default=SensitivityTier.NORMAL)
    operator_tier_override: SensitivityTier | None = None


__all__ = ["DocumentTable"]
