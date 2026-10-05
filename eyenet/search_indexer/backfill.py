# SPDX-License-Identifier: AGPL-3.0-or-later
"""One-shot backfill of ``search_document`` from the existing corpus.

Read-only over the source tables (via the ``session()`` escape hatch, dialect-
free ORM selects), writing only through ``put_search_documents_bulk`` (the
upsert, so re-running is idempotent). Covers the entity types with clean reads:
actor (+aliases), group (+candidates), message, persona, case, document,
artifact, crew. Messages are batched; everything else is entity-scale.

Haystack composition follows GLOBAL_SEARCH.md §1.1. ``handles`` carries
identifiers for the trigram substring index (so ``zfo`` matches ``zfoleaks``).
"""

from __future__ import annotations

import re
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

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository

# Identifiers worth substring-matching: @handles and t.me/<x> links in prose.
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{2,})|t\.me/([A-Za-z0-9_+]{2,})")


def _clean(*parts: str | None) -> str:
    """Join non-empty parts into one haystack string."""
    return " ".join(p for p in parts if p)


def _extract_handles(*texts: str | None) -> str:
    out: list[str] = []
    for t in texts:
        if not t:
            continue
        for a, b in _HANDLE_RE.findall(t):
            out.append(a or b)
    return " ".join(dict.fromkeys(out))  # dedupe, keep order


async def backfill_search(storage: BaseRepository, *, batch: int = 500) -> dict[str, int]:
    """Populate ``search_document`` for every covered entity. Returns per-type counts."""
    counts: dict[str, int] = {}

    # --- load entity-scale tables once (bounded) ---------------------------
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

    # --- actors ------------------------------------------------------------
    rows: list[dict[str, Any]] = []
    for a in actors:
        al = aliases_by_actor.get(a.id, [])
        rows.append(
            {
                "entity_type": "actor",
                "entity_id": a.id,
                "source_id": a.source_id,
                "status": None,
                "title": a.current_handle or a.current_display_name or str(a.id)[:8],
                "subtitle": a.current_display_name,
                "haystack": _clean(
                    a.current_handle,
                    a.current_display_name,
                    a.platform_userid,
                    a.notes,
                    a.operator_assessment,
                    *al,
                ),
                "handles": _clean(a.current_handle, a.platform_userid, *al),
            }
        )
    await storage.put_search_documents_bulk(rows)
    counts["actor"] = len(rows)

    # --- groups (+ candidates as status=candidate) -------------------------
    rows = []
    for g in groups:
        rows.append(
            {
                "entity_type": "group",
                "entity_id": g.id,
                "source_id": g.source_id,
                "status": "joined" if g.id in open_group_ids else "known",
                "title": g.current_title or g.platform_groupid,
                "subtitle": g.kind.value if hasattr(g.kind, "value") else str(g.kind),
                "haystack": _clean(g.current_title, g.current_description, g.platform_groupid),
                "handles": g.platform_groupid,
            }
        )
    for c in candidates:
        rows.append(
            {
                "entity_type": "group",
                "entity_id": c.id,
                "source_id": c.source_id,
                "status": "candidate",
                "title": c.display_name_hint or c.platform_groupid,
                "subtitle": "candidate",
                "haystack": _clean(c.display_name_hint, c.platform_groupid),
                "handles": c.platform_groupid,
            }
        )
    await storage.put_search_documents_bulk(rows)
    counts["group"] = len(rows)

    # --- personas / cases / documents / artifacts / crews ------------------
    rows = [
        {
            "entity_type": "persona",
            "entity_id": p.id,
            "source_id": None,
            "status": None,
            "title": p.label or f"persona {str(p.id)[:8]}",
            "subtitle": f"{len(p.member_actor_ids)} members",
            "haystack": _clean(
                p.label, *[actor_handle.get(UUID(m), "") for m in p.member_actor_ids]
            ),
            "handles": _clean(*[actor_handle.get(UUID(m), "") for m in p.member_actor_ids]),
        }
        for p in personas
    ]
    await storage.put_search_documents_bulk(rows)
    counts["persona"] = len(rows)

    rows = [
        {
            "entity_type": "case",
            "entity_id": c.id,
            "source_id": None,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "title": c.title,
            "subtitle": None,
            "haystack": _clean(c.title, c.description),
            "handles": None,
        }
        for c in cases
    ]
    await storage.put_search_documents_bulk(rows)
    counts["case"] = len(rows)

    rows = [
        {
            "entity_type": "document",
            "entity_id": d.id,
            "source_id": None,
            "status": None,
            "title": d.filename or f"document {str(d.id)[:8]}",
            "subtitle": d.mime,
            "haystack": _clean(d.filename, d.extracted_text),
            "handles": None,
        }
        for d in documents
    ]
    await storage.put_search_documents_bulk(rows)
    counts["document"] = len(rows)

    rows = [
        {
            "entity_type": "artifact",
            "entity_id": a.id,
            "source_id": a.resolved_to_source_id,
            "status": None,
            "title": a.value,
            "subtitle": a.kind.value if hasattr(a.kind, "value") else str(a.kind),
            "haystack": _clean(a.value, a.kind.value if hasattr(a.kind, "value") else str(a.kind)),
            "handles": a.value,
        }
        for a in artifacts
    ]
    await storage.put_search_documents_bulk(rows)
    counts["artifact"] = len(rows)

    rows = [
        {
            "entity_type": "crew",
            "entity_id": cr.id,
            "source_id": None,
            "status": None,
            "title": cr.name,
            "subtitle": f"{len(members_by_crew.get(cr.id, []))} members",
            "haystack": _clean(
                cr.name, cr.notes, *[actor_handle.get(m, "") for m in members_by_crew.get(cr.id, [])]
            ),
            "handles": _clean(*[actor_handle.get(m, "") for m in members_by_crew.get(cr.id, [])]),
        }
        for cr in crews
    ]
    await storage.put_search_documents_bulk(rows)
    counts["crew"] = len(rows)

    # --- messages (batched; haystack = body + group title + author handle) -
    total_msgs = 0
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
        mrows = [
            {
                "entity_type": "message",
                "entity_id": m.id,
                "source_id": m.source_id,
                "status": None,
                "title": (m.body or "")[:80] or f"message {str(m.id)[:8]}",
                "subtitle": _clean(group_title.get(m.group_id), actor_handle.get(m.actor_id)),
                "haystack": _clean(
                    m.body, group_title.get(m.group_id), actor_handle.get(m.actor_id)
                ),
                "handles": _clean(actor_handle.get(m.actor_id), _extract_handles(m.body)),
            }
            for m in msgs
        ]
        await storage.put_search_documents_bulk(mrows)
        total_msgs += len(mrows)
        offset += batch
        if len(msgs) < batch:
            break
    counts["message"] = total_msgs

    return counts


__all__ = ["backfill_search"]
