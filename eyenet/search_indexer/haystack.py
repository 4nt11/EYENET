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


def _iso(dt: Any) -> str | None:
    """ISO-string a datetime for the JSON `fields` bag (datetimes aren't JSON-native)."""
    return dt.isoformat() if dt is not None else None


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
        "fields": {
            "handle": a.current_handle,
            "display_name": a.current_display_name,
            "platform_userid": a.platform_userid,
            "aliases": aliases,
            "last_seen": _iso(a.last_seen_at_source),
        },
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
        "fields": {
            "kind": _enum_value(g.kind),
            "platform_groupid": g.platform_groupid,
            "member_count": g.member_count,
        },
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
        "fields": {"kind": "candidate", "platform_groupid": c.platform_groupid},
    }


#: Full message body carried in the inspector `fields` so an operator reads the
#: WHOLE message (greetz, @mentions, context) — truncating it loses linkage
#: signal. Capped only against a pathological mega-dump paste; a normal forum/
#: chat post is far under this. ponytail: 16k ceiling; stream from a message
#: detail endpoint if full dumps ever need reading in the inspector.
_BODY_MAX = 16000


def message_doc(
    m: MessageTable,
    *,
    group_title: str | None,
    author_handle: str | None,
    container_kind: str | None = None,
) -> dict[str, Any]:
    body = m.body or ""
    return {
        "entity_type": "message",
        "entity_id": m.id,
        "source_id": m.source_id,
        "status": None,
        "title": body[:80] or f"message {str(m.id)[:8]}",
        "subtitle": clean(group_title, author_handle),
        "haystack": clean(m.body, group_title, author_handle),
        "handles": clean(author_handle, extract_handles(m.body)),
        "fields": {
            "author": author_handle,
            "group": group_title,
            # The GroupKind of the message's container, so the graph can split a forum POST
            # (container_kind == 'forum_thread') from a TG MESSAGE. None if the group is gone.
            "container_kind": container_kind,
            "sent_at": _iso(m.sent_at_source),
            "platform_msgid": m.platform_msgid,
            "body": body[:_BODY_MAX] + ("…" if len(body) > _BODY_MAX else ""),
        },
    }


def thread_doc(
    g: GroupTable,
    *,
    op: MessageTable | None,
    op_author_handle: str | None,
    post_count: int,
) -> dict[str, Any]:
    """A forum thread — a group-kinded row, but indexed as its OWN entity_type so
    search keeps thread author / creation date / OP content instead of flattening
    it into a generic group. The OP is the thread's earliest message.
    """
    op_body = (op.body or "") if op is not None else ""
    return {
        "entity_type": "thread",
        "entity_id": g.id,
        "source_id": g.source_id,
        "status": None,  # a thread has no joined/known lifecycle; that's a group facet
        "title": g.current_title or g.platform_groupid,
        "subtitle": clean(op_author_handle, f"{post_count} posts" if post_count else None),
        # OP body IN the haystack so searching the leak announcement finds the thread.
        "haystack": clean(
            g.current_title, g.current_description, g.platform_groupid, op_body, op_author_handle
        ),
        "handles": clean(op_author_handle, extract_handles(op_body), g.platform_groupid),
        "fields": {
            "thread_author": op_author_handle,
            "created": _iso(op.sent_at_source) if op is not None else None,
            "posts": post_count,
            "op": op_body[:_BODY_MAX] + ("…" if len(op_body) > _BODY_MAX else ""),
            "platform_groupid": g.platform_groupid,
        },
    }


def incident_doc(eff: dict[str, Any]) -> dict[str, Any]:
    """Search doc for an effective incident (one per message; see incidents/graph.py). ``eff``
    is the effective-incident dict from storage.effective_incident()."""
    from eyenet.incidents.graph import incident_node_id  # noqa: PLC0415 (avoid import cycle)

    labels = list(eff.get("labels") or [])
    mid = eff["message_id"]
    return {
        "entity_type": "incident",
        "entity_id": incident_node_id(mid),
        "source_id": None,
        "status": eff.get("source"),  # model | operator
        "title": ", ".join(labels) if labels else "incident",
        "subtitle": eff.get("source"),
        "haystack": clean(*labels),
        "handles": None,
        "fields": {
            "labels": labels,
            "source": eff.get("source"),
            "model_version": eff.get("model_version"),
            "message_id": str(mid),
        },
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
        "fields": {"members": len(p.member_actor_ids), "member_handles": member_handles},
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
        "fields": {"status": _enum_value(c.status)},
    }


def document_doc(d: DocumentTable) -> dict[str, Any]:
    # Effective tier: operator override wins over the classifier. Stamped BOTH as the
    # top-level `tier` column (so global search filters uncleared rows out) and in
    # `fields` (so the graph-neighbour hydrate path can clearance-filter a document node).
    tier = _enum_value(d.operator_tier_override or d.classifier_tier)
    return {
        "entity_type": "document",
        "entity_id": d.id,
        "source_id": None,
        "status": None,
        "tier": tier,
        "title": d.filename or f"document {str(d.id)[:8]}",
        "subtitle": d.mime,
        "haystack": clean(d.filename, d.extracted_text),
        "handles": None,
        "fields": {"filename": d.filename, "mime": d.mime, "tier": tier},
    }


def artifact_doc(a: InfrastructureArtifactTable) -> dict[str, Any]:
    kind = _enum_value(a.kind)
    return {
        "entity_type": "artifact",
        "entity_id": a.id,
        "source_id": a.resolved_to_source_id,
        "status": None,
        "kind": kind,  # InfrastructureKind — the first-class sub-type facet
        "title": a.value,
        "subtitle": kind,
        "haystack": clean(a.value, kind),
        "handles": a.value,
        "fields": {"kind": kind, "value": a.value},
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
        "fields": {"members": len(member_handles), "member_handles": member_handles},
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
    "thread_doc",
]
