# SPDX-License-Identifier: AGPL-3.0-or-later
"""GraphExpandMixin — neighbor expansion for the ``/v1/graph/expand`` explorer.

Given ONE node ``(entity_type, entity_id)`` and an enrichment name, return its
neighbours along a single relation, hydrated as ``search_document`` rows so the
wire shape is identical to the search graph (the caller already has the source
node on canvas, so only neighbours + edges come back).

Phase 1 covers the indexed ``EntityType`` set
(actor / group / thread / message / artifact). persona / source / crew / case /
attachment / document are not indexed entity types yet, so they cannot be
hydrated as nodes — those enrichments wait for the slices in
``development/GRAPH_EXPLORER.md`` §6a.

Generic SQLModel ORM only (no dialect leak — [[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_
from sqlmodel import col, select

from eyenet.models import (
    ActorRelationTable,
    InfrastructureArtifactMentionTable,
    LinkageTable,
    MessageTable,
    SearchDocumentTable,
)

from ._helpers import safe_session

# (src entity_type) -> {enrichment name -> derived edge kind}. Also the catalog
# the counts endpoint iterates and the allow-list the expand endpoint validates.
GRAPH_ENRICHMENTS: dict[str, dict[str, str]] = {
    "actor": {
        "messages": "authored",
        "artifacts": "uses_infra",
        "groups": "active_in",
        "linked": "linked",
        "related": "related",
    },
    "artifact": {
        "messages": "mentioned_in",
        "actors": "mentioned_by",
    },
    "message": {
        "author": "authored_by",
        "container": "in",
        "artifacts": "mentions",
    },
    "thread": {
        "messages": "in_thread",
        "participants": "posted_in",
        "op": "started",
    },
    "group": {
        "messages": "in_group",
        "participants": "active_in",
    },
}

# Enrichments that yield at most ONE neighbour (no pagination, no count query).
_SINGLE: frozenset[tuple[str, str]] = frozenset(
    {("message", "author"), ("message", "container"), ("thread", "op")}
)


_M = MessageTable
_MN = InfrastructureArtifactMentionTable


def _actor_select(src_id: UUID, enrichment: str) -> tuple[Any, Any] | None:
    if enrichment == "messages":
        return select(_M.id).where(_M.actor_id == src_id), col(_M.id)
    if enrichment == "artifacts":
        return (
            select(_MN.artifact_id)
            .join(_M, col(_MN.message_id) == col(_M.id))
            .where(_M.actor_id == src_id)
            .distinct()
        ), col(_MN.artifact_id)
    if enrichment == "groups":
        return select(_M.group_id).where(_M.actor_id == src_id).distinct(), col(_M.group_id)
    if enrichment == "linked":
        other = case(
            (col(LinkageTable.actor_a_id) == src_id, col(LinkageTable.actor_b_id)),
            else_=col(LinkageTable.actor_a_id),
        )
        where = or_(col(LinkageTable.actor_a_id) == src_id, col(LinkageTable.actor_b_id) == src_id)
        return select(other).where(where).distinct(), other
    if enrichment == "related":
        other = case(
            (col(ActorRelationTable.from_actor_id) == src_id, col(ActorRelationTable.to_actor_id)),
            else_=col(ActorRelationTable.from_actor_id),
        )
        where = or_(
            col(ActorRelationTable.from_actor_id) == src_id,
            col(ActorRelationTable.to_actor_id) == src_id,
        )
        return select(other).where(where).distinct(), other
    return None


def _artifact_select(src_id: UUID, enrichment: str) -> tuple[Any, Any] | None:
    if enrichment == "messages":
        return select(_MN.message_id).where(_MN.artifact_id == src_id), col(_MN.message_id)
    if enrichment == "actors":
        return (
            select(_M.actor_id)
            .join(_MN, col(_MN.message_id) == col(_M.id))
            .where(_MN.artifact_id == src_id)
            .distinct()
        ), col(_M.actor_id)
    return None


def _message_select(src_id: UUID, enrichment: str) -> tuple[Any, Any] | None:
    if enrichment == "author":
        return select(_M.actor_id).where(_M.id == src_id), col(_M.actor_id)
    if enrichment == "container":
        return select(_M.group_id).where(_M.id == src_id), col(_M.group_id)
    if enrichment == "artifacts":
        return select(_MN.artifact_id).where(_MN.message_id == src_id), col(_MN.artifact_id)
    return None


def _container_select(src_id: UUID, enrichment: str) -> tuple[Any, Any] | None:
    """Thread / group share the same message-container queries."""
    if enrichment == "messages":
        return select(_M.id).where(_M.group_id == src_id), col(_M.id)
    if enrichment == "participants":
        return select(_M.actor_id).where(_M.group_id == src_id).distinct(), col(_M.actor_id)
    if enrichment == "op":
        return (
            select(_M.actor_id)
            .where(_M.group_id == src_id)
            .order_by(col(_M.sent_at_source).asc(), col(_M.id).asc())
            .limit(1)
        ), col(_M.actor_id)
    return None


_SELECTORS = {
    "actor": _actor_select,
    "artifact": _artifact_select,
    "message": _message_select,
    "thread": _container_select,
    "group": _container_select,
}


def _neighbor_select(src_type: str, src_id: UUID, enrichment: str) -> tuple[Any, Any]:
    """``(stmt, id_column)`` selecting the single neighbour-id column for one
    (type, enrichment). Unordered (the caller adds order/limit/offset or wraps
    it in COUNT); the ``op`` case carries its own ordering (a one-row pick)."""
    selector = _SELECTORS.get(src_type)
    result = selector(src_id, enrichment) if selector is not None else None
    if result is None:
        raise ValueError(f"unknown enrichment {src_type!r}.{enrichment!r}")
    return result


class GraphExpandMixin:
    async def _hydrate_nodes(self, session: Any, ids: list[UUID]) -> list[SearchDocumentTable]:
        """search_document rows for ``ids``, in input order; unindexed ids dropped."""
        if not ids:
            return []
        result = await session.exec(
            select(SearchDocumentTable).where(col(SearchDocumentTable.entity_id).in_(ids))
        )
        by_id = {r.entity_id: r for r in result}
        return [by_id[i] for i in ids if i in by_id]

    async def graph_expand(
        self,
        *,
        src_type: str,
        src_id: UUID,
        enrichment: str,
        limit: int,
        offset: int,
        want_total: bool,
    ) -> tuple[list[SearchDocumentTable], list[dict[str, Any]], int | None, bool]:
        """Neighbours of ``(src_type, src_id)`` along ``enrichment``.

        Returns ``(nodes, edges, total, has_more)``. ``edges`` are dicts
        ``{src_id, dst_id, kind}`` (always source -> neighbour). ``total`` is
        ``None`` unless ``want_total``. Raises ``ValueError`` for an unknown
        ``(src_type, enrichment)``.
        """
        catalog = GRAPH_ENRICHMENTS.get(src_type)
        if catalog is None or enrichment not in catalog:
            raise ValueError(f"unknown enrichment {src_type!r}.{enrichment!r}")
        kind = catalog[enrichment]
        single = (src_type, enrichment) in _SINGLE
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            base, idcol = _neighbor_select(src_type, src_id, enrichment)
            if single:
                rows = [r for r in await session.exec(base) if r is not None][:1]
                page_ids, has_more = rows, False
                total = len(rows) if want_total else None
            else:
                paged = base.order_by(idcol).offset(offset).limit(limit + 1)
                fetched = [r for r in await session.exec(paged) if r is not None]
                has_more = len(fetched) > limit
                page_ids = fetched[:limit]
                total = None
                if want_total:
                    total = int(
                        (
                            await session.exec(select(func.count()).select_from(base.subquery()))
                        ).one()
                    )
            nodes = await self._hydrate_nodes(session, page_ids)
            edges = [{"src_id": src_id, "dst_id": n.entity_id, "kind": kind} for n in nodes]
            return nodes, edges, total, has_more

    async def graph_expand_counts(self, *, src_type: str, src_id: UUID) -> dict[str, int]:
        """Per-enrichment neighbour totals for the degree preview. Unknown
        ``src_type`` raises ``ValueError``."""
        catalog = GRAPH_ENRICHMENTS.get(src_type)
        if catalog is None:
            raise ValueError(f"unknown entity type {src_type!r}")
        out: dict[str, int] = {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for enr in catalog:
                base, _idcol = _neighbor_select(src_type, src_id, enr)
                if (src_type, enr) in _SINGLE:
                    out[enr] = len([r for r in await session.exec(base) if r is not None][:1])
                else:
                    out[enr] = int(
                        (
                            await session.exec(select(func.count()).select_from(base.subquery()))
                        ).one()
                    )
        return out
