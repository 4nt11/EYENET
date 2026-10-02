# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared SourceDetail projection for the Sources handlers (M9.D1)."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from eyenet.api.v1.schemas.sources import SourceDetail, SourceDomainView
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.source import SourceRow
from eyenet.storage.repository import BaseRepository


def _base_url_of(idents: object) -> str | None:
    for ident in idents:  # type: ignore[attr-defined]
        base = ident.source_config.get("forum_base_url")
        if base:
            return str(base)
    return None


async def resolve_forum_base_url(storage: BaseRepository, src: SourceRow) -> str | None:
    """A forum source's base URL — it physically lives on the collecting identity's
    ``source_config`` but is logically a property of the forum. Surfacing it lets the
    UI show WHICH forum a (slug-colliding) category belongs to. ``None`` for a
    non-forum source, or a forum with no identity carrying a base URL yet."""
    if src.kind != SourceKind.FORUM:
        return None
    # 1. An identity bound directly to this source (the clean same-source case).
    direct = _base_url_of(await storage.list_identities(source_id=src.id))
    if direct is not None:
        return direct
    # 2. The collector's DISCOVERY source is named "forum:<identity-name>", but the
    #    identity can live under a different INGEST source (the DarkForums two-source
    #    split: groups under forum:darkforums-1, identity under darkforums.as-1).
    #    Identity names are globally unique (UNIQUE constraint), so resolve by name.
    if src.display_name.startswith("forum:"):
        want = src.display_name[len("forum:") :]
        return _base_url_of(i for i in await storage.list_identities() if i.name == want)
    return None


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
        forum_base_url=await resolve_forum_base_url(storage, src),
        notes=src.notes,
        domains=[SourceDomainView.from_domain(d) for d in domains],
        resolved_artifact_count=len(artifacts),
    )
