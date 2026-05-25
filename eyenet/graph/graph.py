"""EYENET Graph — materialises typed nodes and edges from attribution events.

Subscriptions:
  attribution.profile.current    → upsert Actor node
  attribution.linkage.proposed   → upsert Actor nodes + LinkedTo edge (proposed)
  attribution.linkage.suspected  → update LinkedTo edge state
  attribution.linkage.confirmed  → update edge + merge_actors → Persona + emit PersonaUpdated
  attribution.linkage.rejected   → update LinkedTo edge state
  attribution.persona.updated    → idempotent node/edge sync (replay safe)

All handlers use asyncio.create_task (fire-and-forget) matching the Engine/Linker pattern.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import structlog
from opentelemetry import trace

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_PERSONA_UPDATED,
    LinkageConfirmedEnvelope,
    LinkageProposedEnvelope,
    LinkageRejectedEnvelope,
    LinkageSuspectedEnvelope,
    PersonaChangeKind,
    PersonaRow,
    PersonaUpdatedEnvelope,
    ProfileCurrentEnvelope,
)
from eyenet.models.graph import GraphEdgeType, GraphNodeType
from eyenet.service import ServiceBase
from eyenet.telemetry.propagation import attach_from_headers, current_traceparent

_tracer = trace.get_tracer("eyenet.graph")
_log = structlog.get_logger()


class Graph(ServiceBase):
    @property
    def name(self) -> str:
        return "graph"

    @property
    def instance_id(self) -> str:
        return "graph_1"

    async def on_subscribe(self) -> None:
        async def _on_profile(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._on_profile_current(p, h))  # noqa: RUF006

        async def _on_linkage(s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._on_linkage_event(s, p, h))  # noqa: RUF006

        async def _on_persona(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._on_persona_updated(p, h))  # noqa: RUF006

        await self._bus.subscribe("attribution.profile.current", _on_profile)
        await self._bus.subscribe("attribution.linkage.>", _on_linkage)
        await self._bus.subscribe("attribution.persona.updated", _on_persona)

    # -- profile.current -------------------------------------------------------

    async def _on_profile_current(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            await self._on_profile_current_inner(payload)

    async def _on_profile_current_inner(self, payload: bytes) -> None:
        try:
            env = ProfileCurrentEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.profile_parse_error", error=str(exc))
            return

        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={
                "service.name": self.name,
                "graph.op": "node_upsert",
                "graph.node_type": GraphNodeType.ACTOR,
                "graph.node_id": str(env.actor_id),
                "graph.source_event": "attribution.profile.current",
            },
        ):
            await self._storage.upsert_graph_node(
                GraphNodeType.ACTOR,
                env.actor_id,
                {
                    "role_signal": env.role_signal,
                    "role_confidence": env.role_confidence,
                    "derived_at": env.derived_at.isoformat(),
                    "profile_version": env.version,
                },
            )

    # -- linkage events --------------------------------------------------------

    async def _on_linkage_event(
        self, subject: str, payload: bytes, headers: dict[str, str]
    ) -> None:
        with attach_from_headers(headers):
            await self._on_linkage_event_inner(subject, payload)

    async def _on_linkage_event_inner(self, subject: str, payload: bytes) -> None:
        if subject == "attribution.linkage.proposed":
            await self._handle_proposed(payload)
        elif subject == "attribution.linkage.suspected":
            await self._handle_suspected(payload)
        elif subject == "attribution.linkage.confirmed":
            await self._handle_confirmed(payload)
        elif subject == "attribution.linkage.rejected":
            await self._handle_rejected(payload)
        else:
            _log.debug("graph.unknown_linkage_subject", subject=subject)

    async def _handle_proposed(self, payload: bytes) -> None:
        try:
            env = LinkageProposedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.proposed_parse_error", error=str(exc))
            return

        now = datetime.now(tz=UTC)

        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={"graph.op": "edge_upsert", "graph.edge_type": GraphEdgeType.LINKED_TO},
        ):
            await self._storage.upsert_graph_node(GraphNodeType.ACTOR, env.actor_a_id, {})
            await self._storage.upsert_graph_node(GraphNodeType.ACTOR, env.actor_b_id, {})
            await self._storage.upsert_graph_edge(
                GraphEdgeType.LINKED_TO,
                env.actor_a_id,
                env.actor_b_id,
                {
                    "state": "proposed",
                    "method": env.method,
                    "score": env.score,
                    "linkage_id": str(env.linkage_id),
                    "updated_at": now.isoformat(),
                },
            )

    async def _handle_suspected(self, payload: bytes) -> None:
        try:
            env = LinkageSuspectedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.suspected_parse_error", error=str(exc))
            return

        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={
                "service.name": self.name,
                "graph.op": "edge_upsert",
                "graph.edge_type": GraphEdgeType.LINKED_TO,
                "graph.source_event": "attribution.linkage.suspected",
                "linkage.id": str(env.linkage_id),
            },
        ):
            await self._storage.upsert_graph_edge(
                GraphEdgeType.LINKED_TO,
                env.actor_a_id,
                env.actor_b_id,
                {
                    "state": "suspected",
                    "decided_by": env.decided_by,
                    "linkage_id": str(env.linkage_id),
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

    async def _handle_confirmed(self, payload: bytes) -> None:
        try:
            env = LinkageConfirmedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.confirmed_parse_error", error=str(exc))
            return

        now = datetime.now(tz=UTC)

        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={
                "service.name": self.name,
                "graph.op": "merge",
                "graph.source_event": "attribution.linkage.confirmed",
                "linkage.id": str(env.linkage_id),
            },
        ) as confirmed_span:
            await self._storage.upsert_graph_edge(
                GraphEdgeType.LINKED_TO,
                env.actor_a_id,
                env.actor_b_id,
                {
                    "state": "confirmed",
                    "decided_by": env.decided_by,
                    "linkage_id": str(env.linkage_id),
                    "updated_at": now.isoformat(),
                },
            )

            # Persona aggregation — union-find merge
            persona_row = cast(
                "PersonaRow",
                await self._storage.merge_actors_into_persona(
                    env.actor_a_id,
                    env.actor_b_id,
                    via_linkage_id=env.linkage_id,
                ),
            )

            persona_id = persona_row.id
            member_ids = persona_row.member_actor_ids
            confirmed_span.set_attribute("persona.id", str(persona_id))
            confirmed_span.set_attribute("persona.member_count", len(member_ids))

            # Upsert Persona node
            await self._storage.upsert_graph_node(
                GraphNodeType.PERSONA,
                persona_id,
                {
                    "member_count": len(member_ids),
                    "updated_at": now.isoformat(),
                },
            )
            # Upsert BelongsToPersona edges for all current members
            for actor_id in member_ids:
                await self._storage.upsert_graph_edge(
                    GraphEdgeType.BELONGS_TO_PERSONA,
                    actor_id,
                    persona_id,
                    {"joined_at": now.isoformat()},
                )

        # Emit PersonaUpdated
        tc = _make_trace_context()
        updated_env = PersonaUpdatedEnvelope(
            trace_context=tc,
            persona_id=persona_id,
            member_actor_ids=member_ids,
            change_kind=PersonaChangeKind.MEMBERS_ADDED
            if len(member_ids) > 2  # noqa: PLR2004
            else PersonaChangeKind.CREATED,
            via_linkage_id=env.linkage_id,
            at=now,
        )
        await self.publisher.publish(SUBJECT_PERSONA_UPDATED, updated_env)

        await self.audit.emit(
            event="persona.merged",
            subject_kind="persona",
            subject_id=persona_id,
            payload={
                "member_actor_ids": [str(aid) for aid in member_ids],
                "via_linkage_id": str(env.linkage_id),
            },
        )

        _log.info(
            "graph.persona_merged",
            persona_id=str(persona_id),
            member_count=len(member_ids),
        )

    async def _handle_rejected(self, payload: bytes) -> None:
        try:
            env = LinkageRejectedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.rejected_parse_error", error=str(exc))
            return

        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={
                "service.name": self.name,
                "graph.op": "edge_upsert",
                "graph.edge_type": GraphEdgeType.LINKED_TO,
                "graph.source_event": "attribution.linkage.rejected",
                "linkage.id": str(env.linkage_id),
            },
        ):
            await self._storage.upsert_graph_edge(
                GraphEdgeType.LINKED_TO,
                env.actor_a_id,
                env.actor_b_id,
                {
                    "state": "rejected",
                    "decided_by": env.decided_by,
                    "linkage_id": str(env.linkage_id),
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

    # -- persona.updated (idempotent replay) -----------------------------------

    async def _on_persona_updated(self, payload: bytes, headers: dict[str, str]) -> None:
        with attach_from_headers(headers):
            await self._on_persona_updated_inner(payload)

    async def _on_persona_updated_inner(self, payload: bytes) -> None:
        try:
            env = PersonaUpdatedEnvelope.model_validate_json(payload)
        except Exception as exc:
            _log.error("graph.persona_updated_parse_error", error=str(exc))
            return

        now = datetime.now(tz=UTC)
        with _tracer.start_as_current_span(
            "graph.upsert",
            attributes={
                "service.name": self.name,
                "graph.op": "persona_upsert",
                "graph.source_event": "attribution.persona.updated",
                "persona.id": str(env.persona_id),
                "persona.member_count": len(env.member_actor_ids),
            },
        ):
            await self._storage.upsert_graph_node(
                GraphNodeType.PERSONA,
                env.persona_id,
                {"member_count": len(env.member_actor_ids), "updated_at": now.isoformat()},
            )
            for actor_id in env.member_actor_ids:
                await self._storage.upsert_graph_edge(
                    GraphEdgeType.BELONGS_TO_PERSONA,
                    actor_id,
                    env.persona_id,
                    {"joined_at": now.isoformat()},
                )


def _make_trace_context() -> TraceContext:
    tp = current_traceparent()
    if tp is None:
        tp = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"
    return TraceContext(traceparent=tp)


__all__ = ["Graph"]
