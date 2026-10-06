# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot backfill of ``search_document`` from the existing corpus.

Read-only over the source tables (via the ``session()`` escape hatch, dialect-
free ORM selects), writing only through ``put_search_documents_bulk`` (the
upsert, so re-running is idempotent). Covers the entity types with clean reads:
actor (+aliases), group (+candidates), message, persona, case, document,
artifact, crew.

Operates against the LIVE operating DB while collectors + the SearchIndexer are
also writing, so it is built for contention:
  * every bulk write is retried with backoff on a transient SQLite lock;
  * messages are indexed **resumably** — each batch selects the next messages
    NOT yet in ``search_document`` (index-backed ``NOT EXISTS``), so a re-run
    only fills the gap left by an interrupted run instead of re-indexing all.

Payloads come from the shared builders in ``haystack.py`` (the same ones the live
SearchIndexer uses), so backfill and live indexing never drift.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import exists
from sqlalchemy.exc import OperationalError
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
    SearchDocumentTable,
)
from eyenet.search_indexer import haystack

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eyenet.storage.repository import BaseRepository

_RETRY_ATTEMPTS = 6


async def _bulk(storage: BaseRepository, rows: Sequence[dict[str, Any]]) -> None:
    """Upsert a batch, retrying on a transient SQLite lock (live-DB contention)."""
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            await storage.put_search_documents_bulk(rows)
            return
        except OperationalError as exc:
            msg = str(exc).lower()
            if attempt == _RETRY_ATTEMPTS - 1 or ("locked" not in msg and "busy" not in msg):
                raise
            await asyncio.sleep(0.5 * (attempt + 1))


async def backfill_search(
    storage: BaseRepository, *, batch: int = 500, full: bool = False
) -> dict[str, int]:
    """Populate ``search_document`` for every covered entity. Returns per-type counts.

    ``full=True`` re-indexes every message (not just un-indexed ones) — needed after
    a schema change to the message payload (e.g. the new ``fields`` column), where
    existing rows must be rewritten. Default re-fills only the gap (resume).
    """
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

    await _bulk(storage, [haystack.actor_doc(a, aliases_by_actor.get(a.id, [])) for a in actors])
    counts["actor"] = len(actors)

    group_rows: list[dict[str, Any]] = [
        haystack.group_doc(g, status="joined" if g.id in open_group_ids else "known")
        for g in groups
    ]
    group_rows += [haystack.candidate_group_doc(c) for c in candidates]
    await _bulk(storage, group_rows)
    counts["group"] = len(group_rows)

    await _bulk(
        storage,
        [
            haystack.persona_doc(p, [actor_handle.get(UUID(m), "") for m in p.member_actor_ids])
            for p in personas
        ],
    )
    counts["persona"] = len(personas)

    await _bulk(storage, [haystack.case_doc(c) for c in cases])
    counts["case"] = len(cases)

    await _bulk(storage, [haystack.document_doc(d) for d in documents])
    counts["document"] = len(documents)

    await _bulk(storage, [haystack.artifact_doc(a) for a in artifacts])
    counts["artifact"] = len(artifacts)

    await _bulk(
        storage,
        [
            haystack.crew_doc(cr, [actor_handle.get(m, "") for m in members_by_crew.get(cr.id, [])])
            for cr in crews
        ],
    )
    counts["crew"] = len(crews)

    counts["message"] = await _backfill_messages(storage, group_title, actor_handle, batch, full)
    return counts


async def _backfill_messages(
    storage: BaseRepository,
    group_title: dict[UUID, str],
    actor_handle: dict[UUID, str],
    batch: int,
    full: bool,
) -> int:
    """Index messages via keyset pagination (id ascending), O(n) single pass.

    ``full=False`` skips messages already in search_document (resume a gap);
    ``full=True`` re-upserts every message (rewrite after a payload schema change).
    Keyset (``id > last_id``) avoids OFFSET/NOT-EXISTS-from-start quadratics.
    """
    total = 0
    last_id = UUID(int=0)
    already_indexed = (
        select(SearchDocumentTable.id)
        .where(
            SearchDocumentTable.entity_type == "message",
            SearchDocumentTable.entity_id == MessageTable.id,
        )
        .correlate(MessageTable)
    )
    while True:
        async with storage.session() as s:
            stmt = select(MessageTable).where(col(MessageTable.id) > last_id)
            if not full:
                stmt = stmt.where(~exists(already_indexed))
            msgs = list(await s.exec(stmt.order_by(col(MessageTable.id)).limit(batch)))
        if not msgs:
            break
        last_id = msgs[-1].id
        await _bulk(
            storage,
            [
                haystack.message_doc(
                    m,
                    group_title=group_title.get(m.group_id),
                    author_handle=actor_handle.get(m.actor_id),
                )
                for m in msgs
            ],
        )
        total += len(msgs)
    return total


__all__ = ["backfill_search"]
