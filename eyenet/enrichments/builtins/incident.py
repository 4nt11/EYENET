# SPDX-License-Identifier: AGPL-3.0-or-later
"""<entity> -> its INCIDENT classifications (IncidentTable, per-message multi-label).

A message carries 0+ incident classifications (the mmBERT cascade's fired label set);
thread/actor fan out over their messages. Incidents are NOT search-indexed, so (like the
source/domain enrichments) these synthesize the incident node straight from IncidentTable
rather than hydrating from search_document.

Incident is the one entity that pops RED (--etype-incident) - it's the signal.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.models import IncidentTable, MessageTable

if TYPE_CHECKING:
    from uuid import UUID

_I = IncidentTable
_M = MessageTable


def _incident_node(inc: IncidentTable) -> ExpandNode:
    labels = list(inc.labels or [])
    return ExpandNode(
        entity_type="incident",
        entity_id=inc.id,
        title=", ".join(labels) if labels else "unclassified",
        status=None,
        source_id=None,
        fields={
            "labels": labels,
            "scores": inc.scores or {},
            "model_version": inc.model_version,
            "message_id": str(inc.message_id),
            "classified_at": inc.classified_at.isoformat() if inc.classified_at else None,
        },
    )


class _IncidentEnrichment(Enrichment):
    """Shared <entity> -> incidents hop. Abstract (no ``_incident_filter``), so autodiscovery
    registers only the concrete per-src_type subclasses."""

    name = "incidents"
    output_type = "incident"
    countable = True

    @abstractmethod
    def _incident_filter(self, src_id: UUID) -> Any:
        """A WHERE clause over IncidentTable selecting this source's incidents."""

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        base = select(_I).where(self._incident_filter(src_id))
        paged = base.order_by(col(_I.classified_at).desc()).offset(offset).limit(limit + 1)
        rows = list(await ctx.session.exec(paged))
        has_more = len(rows) > limit
        nodes = [_incident_node(i) for i in rows[:limit]]
        total = None
        if want_total:
            total = int(
                (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
            )
        edges = [{"src_id": src_id, "dst_id": n.entity_id, "kind": self.edge_kind} for n in nodes]
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        base = select(_I).where(self._incident_filter(src_id))
        return int(
            (await ctx.session.exec(select(func.count()).select_from(base.subquery()))).one()
        )


class MessageIncidents(_IncidentEnrichment):
    src_type = "message"
    edge_kind = "classified_as"

    def _incident_filter(self, src_id: UUID) -> Any:
        return col(_I.message_id) == src_id


class ThreadIncidents(_IncidentEnrichment):
    src_type = "thread"
    edge_kind = "has_incident"

    def _incident_filter(self, src_id: UUID) -> Any:
        return col(_I.message_id).in_(select(_M.id).where(col(_M.group_id) == src_id))


class ActorIncidents(_IncidentEnrichment):
    src_type = "actor"
    edge_kind = "has_incident"

    def _incident_filter(self, src_id: UUID) -> Any:
        return col(_I.message_id).in_(select(_M.id).where(col(_M.actor_id) == src_id))
