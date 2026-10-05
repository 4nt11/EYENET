# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure haystack builders — one search_document payload per entity (GLOBAL_SEARCH.md §1.1).

Shared by the one-shot backfill and the live SearchIndexer so the two never
drift. Each builder takes an ORM row plus any denormalized context the row can't
supply (aliases, a group title, member handles) and returns the kwargs dict for
``put_search_document``. ``updated_at`` is filled by the storage layer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eyenet.models import (
        ActorTable,
        CaseTable,
        DocumentTable,
        GroupCandidateTable,
        GroupTable,
        InfrastructureArtifactTable,
        ManualCrewTable,
        MessageTable,
        PersonaTable,
    )

# Identifiers worth substring-matching in prose: @handles and t.me/<x> links.
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{2,})|t\.me/([A-Za-z0-9_+]{2,})")


def clean(*parts: str | None) -> str:
    """Join the non-empty parts into one haystack string."""
    return " ".join(p for p in parts if p)


def extract_handles(*texts: str | None) -> str:
    """Pull @handles / t.me targets out of prose, deduped, order-preserving."""
    out: list[str] = []
    for t in texts:
        if not t:
            continue
        for a, b in _HANDLE_RE.findall(t):
            out.append(a or b)
    return " ".join(dict.fromkeys(out))


def _enum_value(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


def actor_doc(a: ActorTable, aliases: list[str]) -> dict[str, Any]:
    return {
        "entity_type": "actor",
        "entity_id": a.id,
        "source_id": a.source_id,
        "status": None,
        "title": a.current_handle or a.current_display_name or str(a.id)[:8],
        "subtitle": a.current_display_name,
        "haystack": clean(
            a.current_handle,
            a.current_display_name,
            a.platform_userid,
            a.notes,
            a.operator_assessment,
            *aliases,
        ),
        "handles": clean(a.current_handle, a.platform_userid, *aliases),
    }


def group_doc(g: GroupTable, *, status: str) -> dict[str, Any]:
    return {
        "entity_type": "group",
        "entity_id": g.id,
        "source_id": g.source_id,
        "status": status,
        "title": g.current_title or g.platform_groupid,
        "subtitle": _enum_value(g.kind),
        "haystack": clean(g.current_title, g.current_description, g.platform_groupid),
        "handles": g.platform_groupid,
    }


def candidate_group_doc(c: GroupCandidateTable) -> dict[str, Any]:
    return {
        "entity_type": "group",
        "entity_id": c.id,
        "source_id": c.source_id,
        "status": "candidate",
        "title": c.display_name_hint or c.platform_groupid,
        "subtitle": "candidate",
        "haystack": clean(c.display_name_hint, c.platform_groupid),
        "handles": c.platform_groupid,
    }


def message_doc(
    m: MessageTable, *, group_title: str | None, author_handle: str | None
) -> dict[str, Any]:
    return {
        "entity_type": "message",
        "entity_id": m.id,
        "source_id": m.source_id,
        "status": None,
        "title": (m.body or "")[:80] or f"message {str(m.id)[:8]}",
        "subtitle": clean(group_title, author_handle),
        "haystack": clean(m.body, group_title, author_handle),
        "handles": clean(author_handle, extract_handles(m.body)),
    }


def persona_doc(p: PersonaTable, member_handles: list[str]) -> dict[str, Any]:
    return {
        "entity_type": "persona",
        "entity_id": p.id,
        "source_id": None,
        "status": None,
        "title": p.label or f"persona {str(p.id)[:8]}",
        "subtitle": f"{len(p.member_actor_ids)} members",
        "haystack": clean(p.label, *member_handles),
        "handles": clean(*member_handles),
    }


def case_doc(c: CaseTable) -> dict[str, Any]:
    return {
        "entity_type": "case",
        "entity_id": c.id,
        "source_id": None,
        "status": _enum_value(c.status),
        "title": c.title,
        "subtitle": None,
        "haystack": clean(c.title, c.description),
        "handles": None,
    }


def document_doc(d: DocumentTable) -> dict[str, Any]:
    return {
        "entity_type": "document",
        "entity_id": d.id,
        "source_id": None,
        "status": None,
        "title": d.filename or f"document {str(d.id)[:8]}",
        "subtitle": d.mime,
        "haystack": clean(d.filename, d.extracted_text),
        "handles": None,
    }


def artifact_doc(a: InfrastructureArtifactTable) -> dict[str, Any]:
    kind = _enum_value(a.kind)
    return {
        "entity_type": "artifact",
        "entity_id": a.id,
        "source_id": a.resolved_to_source_id,
        "status": None,
        "title": a.value,
        "subtitle": kind,
        "haystack": clean(a.value, kind),
        "handles": a.value,
    }


def crew_doc(cr: ManualCrewTable, member_handles: list[str]) -> dict[str, Any]:
    return {
        "entity_type": "crew",
        "entity_id": cr.id,
        "source_id": None,
        "status": None,
        "title": cr.name,
        "subtitle": f"{len(member_handles)} members",
        "haystack": clean(cr.name, cr.notes, *member_handles),
        "handles": clean(*member_handles),
    }


__all__ = [
    "actor_doc",
    "artifact_doc",
    "candidate_group_doc",
    "case_doc",
    "clean",
    "crew_doc",
    "document_doc",
    "extract_handles",
    "group_doc",
    "message_doc",
    "persona_doc",
]
