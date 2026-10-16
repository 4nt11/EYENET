# SPDX-License-Identifier: AGPL-3.0-or-later
"""Document-source enrichment: artifacts extracted from the document's text.

``tier_gated`` - a document carries a sensitivity tier, and documents are not
search-indexed, so this is the only place a document's derived data surfaces in
the graph. The API gates it on the document's effective tier before expanding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import LocalSQLEnrichment
from eyenet.models import DocumentArtifactTable

if TYPE_CHECKING:
    from uuid import UUID


class DocumentArtifacts(LocalSQLEnrichment):
    src_type = "document"
    name = "artifacts"
    output_type = "artifact"
    edge_kind = "contains_artifact"
    tier_gated = True

    def build_select(self, src_id: UUID) -> tuple[Any, Any]:
        return (
            select(DocumentArtifactTable.artifact_id).where(
                DocumentArtifactTable.document_id == src_id
            ),
            col(DocumentArtifactTable.artifact_id),
        )
