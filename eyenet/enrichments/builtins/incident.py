# SPDX-License-Identifier: AGPL-3.0-or-later
"""<entity> -> its INCIDENT(s) (the effective per-message classification).

An incident is one per message: the operator correction (IncidentLabelTable) if present,
else the latest model classification (IncidentTable); empty operator labels = false
positive = no incident. message/thread/actor fan out over their messages. The effective
view + scope join live in storage (``effective_incidents_for_scope``); this enrichment just
synthesizes the nodes with the shared deterministic id so they match the search index.

Incident is the one entity that pops RED (--etype-incident) - it's the signal.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from eyenet.enrichments.base import Enrichment, ExpandContext, ExpandNode, ExpandResult
from eyenet.incidents.graph import incident_node_id
from eyenet.models import MessageTable

if TYPE_CHECKING:
    from uuid import UUID


def _incident_node(d: dict[str, Any], snippet: str | None) -> ExpandNode:
    labels = list(d.get("labels") or [])
    mid = d["message_id"]
    return ExpandNode(
        entity_type="incident",
        entity_id=incident_node_id(mid),
        title=", ".join(labels) if labels else "incident",
        status=None,
        source_id=None,
        fields={
            "labels": labels,
            "source": d.get("source"),
            "model_version": d.get("model_version"),
            "scores": d.get("scores") or {},
            "message_id": str(mid),
            "message": snippet,  # body preview, so the incident shows what it is about
            "decided_by": d.get("decided_by"),
        },
    )


class _IncidentEnrichment(Enrichment):
    """Shared <entity> -> incidents hop. Abstract (no ``_scope``), so autodiscovery registers
    only the concrete per-src_type subclasses."""

    name = "incidents"
    output_type = "incident"
    countable = True

    @abstractmethod
    def _scope(self, src_id: UUID) -> dict[str, UUID]:
        """The scope kwarg for effective_incidents_for_scope (message/group/actor id)."""

    async def neighbors(
        self, ctx: ExpandContext, src_id: UUID, *, limit: int, offset: int, want_total: bool
    ) -> ExpandResult:
        page, total, has_more = await ctx.repo.effective_incidents_for_scope(
            **self._scope(src_id), limit=limit, offset=offset, want_total=want_total
        )
        # Body previews for the page's messages, so a floating incident still shows context.
        mids = [d["message_id"] for d in page]
        snippets: dict[Any, str] = {}
        if mids:
            for mid_, body in await ctx.session.exec(
                select(MessageTable.id, MessageTable.body).where(col(MessageTable.id).in_(mids))
            ):
                snippets[mid_] = (body or "")[:80]
        nodes: list[ExpandNode] = []
        edges: list[dict[str, Any]] = []
        for d in page:
            node = _incident_node(d, snippets.get(d["message_id"]))
            nodes.append(node)
            mid = d["message_id"]
            # Always tie the incident to its MESSAGE (auto-links to that node if it's on the
            # canvas - the induced-subgraph guard drops it otherwise). When the source IS the
            # message this already connects it; the src edge below would dedup to the same.
            edges.append({"src_id": mid, "dst_id": node.entity_id, "kind": "classified_as"})
            # For actor/thread fan-out, also edge the source straight to the incident.
            if src_id != mid:
                edges.append({"src_id": src_id, "dst_id": node.entity_id, "kind": self.edge_kind})
        return ExpandResult(nodes=nodes, edges=edges, total=total, has_more=has_more)

    async def count(self, ctx: ExpandContext, src_id: UUID) -> int:
        _page, total, _more = await ctx.repo.effective_incidents_for_scope(
            **self._scope(src_id), limit=0, offset=0, want_total=True
        )
        return int(total or 0)


class MessageIncidents(_IncidentEnrichment):
    src_type = "message"
    edge_kind = "classified_as"

    def _scope(self, src_id: UUID) -> dict[str, UUID]:
        return {"message_id": src_id}


class ThreadIncidents(_IncidentEnrichment):
    src_type = "thread"
    edge_kind = "has_incident"

    def _scope(self, src_id: UUID) -> dict[str, UUID]:
        return {"group_id": src_id}


class ActorIncidents(_IncidentEnrichment):
    src_type = "actor"
    edge_kind = "has_incident"

    def _scope(self, src_id: UUID) -> dict[str, UUID]:
        return {"actor_id": src_id}
