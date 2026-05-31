# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wire schemas for the document upload surface (M10 slice 7)."""

from __future__ import annotations

from uuid import UUID

from eyenet.contracts.enums import SensitivityTier

from ._base import ApiSchema


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


__all__ = ["DocumentUploadResult"]
