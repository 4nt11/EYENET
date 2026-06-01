# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared SourceDetail projection for the Sources handlers (M9.D1)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from eyenet.api.v1.schemas.sources import SourceDetail, SourceDomainView
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository


async def build_source_detail(storage: BaseRepository, source_id: UUID) -> SourceDetail | None:
    """Assemble the full :class:`SourceDetail` for a source, or ``None`` if absent.

    Active domains are inlined; ``resolved_artifact_count`` is the number of
    InfrastructureArtifacts resolved to this Source (the per-source bucket of
    the bridge summary).
    """
    src = cast("SourceRow | None", await storage.get_source(source_id))
    if src is None:
        return None
    domains = await storage.list_source_domains(source_id=source_id)
    artifacts = await storage.list_artifacts_for_source(source_id)
    return SourceDetail(
        source_id=src.id,
        kind=src.kind,
        display_name=src.display_name,
        canonical_url=src.canonical_url,
        created_at=src.created_at,
        active_domain_count=len(domains),
        notes=src.notes,
        domains=[SourceDomainView.from_domain(d) for d in domains],
        resolved_artifact_count=len(artifacts),
    )
