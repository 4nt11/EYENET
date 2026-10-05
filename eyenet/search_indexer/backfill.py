# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot backfill of ``search_document`` from the existing corpus.

Read-only over the source tables (via the ``session()`` escape hatch, dialect-
free ORM selects), writing only through ``put_search_documents_bulk`` (the
upsert, so re-running is idempotent). Covers the entity types with clean reads:
actor (+aliases), group (+candidates), message, persona, case, document,
artifact, crew. Messages are batched; everything else is entity-scale.

Payloads come from the shared builders in ``haystack.py`` (the same ones the live
SearchIndexer uses), so backfill and live indexing never drift.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlmodel import col, select

from eyenet.models import (
    ActorAliasHistoryTable,
    ActorTable,
    CaseTable,
    CollectorGroupMembershipTable,
    DocumentTable,
    GroupCandidateTable,
    GroupTable,
    InfrastructureArtifactTable,
    ManualCrewMemberTable,
    ManualCrewTable,
    MessageTable,
    PersonaTable,
)
from eyenet.search_indexer import haystack

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository


async def backfill_search(storage: BaseRepository, *, batch: int = 500) -> dict[str, int]:
    """Populate ``search_document`` for every covered entity. Returns per-type counts."""
    counts: dict[str, int] = {}

    async with storage.session() as s:
        actors = list(await s.exec(select(ActorTable)))
        aliases = list(await s.exec(select(ActorAliasHistoryTable)))
        groups = list(await s.exec(select(GroupTable)))
        candidates = list(await s.exec(select(GroupCandidateTable)))
        open_group_ids = set(
            await s.exec(
                select(CollectorGroupMembershipTable.group_id).where(
                    col(CollectorGroupMembershipTable.left_at).is_(None)
                )
            )
        )
        personas = list(await s.exec(select(PersonaTable)))
        cases = list(await s.exec(select(CaseTable)))
        documents = list(await s.exec(select(DocumentTable)))
        artifacts = list(await s.exec(select(InfrastructureArtifactTable)))
        crews = list(await s.exec(select(ManualCrewTable)))
        crew_members = list(await s.exec(select(ManualCrewMemberTable)))

    actor_handle: dict[UUID, str] = {
        a.id: (a.current_handle or a.current_display_name or str(a.id)[:8]) for a in actors
    }
    group_title: dict[UUID, str] = {g.id: (g.current_title or "") for g in groups}
    aliases_by_actor: dict[UUID, list[str]] = defaultdict(list)
    for al in aliases:
        aliases_by_actor[al.actor_id].append(al.value)
    members_by_crew: dict[UUID, list[UUID]] = defaultdict(list)
    for cm in crew_members:
        members_by_crew[cm.crew_id].append(cm.actor_id)

    await storage.put_search_documents_bulk(
        [haystack.actor_doc(a, aliases_by_actor.get(a.id, [])) for a in actors]
    )
    counts["actor"] = len(actors)

    group_rows: list[dict[str, Any]] = [
        haystack.group_doc(g, status="joined" if g.id in open_group_ids else "known")
        for g in groups
    ]
    group_rows += [haystack.candidate_group_doc(c) for c in candidates]
    await storage.put_search_documents_bulk(group_rows)
    counts["group"] = len(group_rows)

    await storage.put_search_documents_bulk(
        [
            haystack.persona_doc(p, [actor_handle.get(UUID(m), "") for m in p.member_actor_ids])
            for p in personas
        ]
    )
    counts["persona"] = len(personas)

    await storage.put_search_documents_bulk([haystack.case_doc(c) for c in cases])
    counts["case"] = len(cases)

    await storage.put_search_documents_bulk([haystack.document_doc(d) for d in documents])
    counts["document"] = len(documents)

    await storage.put_search_documents_bulk([haystack.artifact_doc(a) for a in artifacts])
    counts["artifact"] = len(artifacts)

    await storage.put_search_documents_bulk(
        [
            haystack.crew_doc(cr, [actor_handle.get(m, "") for m in members_by_crew.get(cr.id, [])])
            for cr in crews
        ]
    )
    counts["crew"] = len(crews)

    counts["message"] = await _backfill_messages(storage, group_title, actor_handle, batch)
    return counts


async def _backfill_messages(
    storage: BaseRepository,
    group_title: dict[UUID, str],
    actor_handle: dict[UUID, str],
    batch: int,
) -> int:
    """Index messages in batches via the shared message builder."""
    total = 0
    offset = 0
    while True:
        async with storage.session() as s:
            msgs = list(
                await s.exec(
                    select(MessageTable).order_by(col(MessageTable.id)).limit(batch).offset(offset)
                )
            )
        if not msgs:
            break
        await storage.put_search_documents_bulk(
            [
                haystack.message_doc(
                    m,
                    group_title=group_title.get(m.group_id),
                    author_handle=actor_handle.get(m.actor_id),
                )
                for m in msgs
            ]
        )
        total += len(msgs)
        offset += batch
        if len(msgs) < batch:
            break
    return total


__all__ = ["backfill_search"]
