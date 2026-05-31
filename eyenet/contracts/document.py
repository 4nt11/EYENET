"""`Document` contract (M10 slice 7).

A standalone uploaded artifact classified at ingest. Field-parity with
`eyenet.models.document.DocumentTable` so the storage mixin can round-trip via
`DocumentTable(**row.model_dump())` / `DocumentRow.model_validate(...)`.

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from ._base import DbRowBase
from .enums import SensitivityTier


class DocumentRow(DbRowBase):
    """Persisted uploaded document + its settled classification (MODELS §2.10)."""

    sha256: str
    mime: str
    size_bytes: int
    doc_kind: str | None = None
    filename: str | None = None
    storage_uri: str | None = None
    extracted_text: str | None = None
    embedded_meta: dict[str, Any] = Field(default_factory=dict)
    classification: dict[str, Any] = Field(default_factory=dict)
    review_required: bool = False
    uploaded_by_user_id: UUID | None = None
    uploaded_at: datetime
    ingested_at: datetime
    classifier_tier: SensitivityTier = SensitivityTier.NORMAL
    operator_tier_override: SensitivityTier | None = None


__all__ = ["DocumentRow"]
