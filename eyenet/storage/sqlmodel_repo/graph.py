# SPDX-License-Identifier: AGPL-3.0-or-later
"""GraphMixin — typed SQLModel-backed graph store."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import func, text
from sqlmodel import col, select

from eyenet.models.graph import (
    GraphEdgeTable,
    GraphEdgeType,
    GraphNodeTable,
    GraphNodeType,
)

from ._helpers import safe_session

_tracer = trace.get_tracer("eyenet.storage.sqlmodel_repo.graph")


class GraphMixin:
    async def upsert_graph_node(
        self,
        node_type: str,
        node_id: UUID,
        attrs: dict[str, object],
    ) -> None:
        now = datetime.now(tz=UTC)
        ntype = GraphNodeType(node_type)
        with _tracer.start_as_current_span(
            "storage.graph.upsert_node",
            attributes={
                "graph.node_type": ntype.value,
                "graph.node_id": str(node_id),
            },
        ):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                result = await session.exec(
                    select(GraphNodeTable).where(
                        col(GraphNodeTable.node_id) == node_id,
                        col(GraphNodeTable.node_type) == ntype,
                    )
                )
                existing = result.first()
                if existing is None:
                    session.add(
                        GraphNodeTable(
                            node_id=node_id, node_type=ntype, attrs=attrs, updated_at=now
                        )
                    )
                else:
                    existing.attrs = {**existing.attrs, **attrs}
                    existing.updated_at = now
                    session.add(existing)
                await session.commit()

    async def upsert_graph_edge(
        self,
        edge_type: str,
        src_id: UUID,
        dst_id: UUID,
        attrs: dict[str, object],
    ) -> None:
        now = datetime.now(tz=UTC)
        etype = GraphEdgeType(edge_type)
        with _tracer.start_as_current_span(
            "storage.graph.upsert_edge",
            attributes={
                "graph.edge_type": etype.value,
                "graph.src_id": str(src_id),
                "graph.dst_id": str(dst_id),
            },
        ):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                result = await session.exec(
                    select(GraphEdgeTable).where(
                        col(GraphEdgeTable.edge_type) == etype,
                        col(GraphEdgeTable.src_id) == src_id,
                        col(GraphEdgeTable.dst_id) == dst_id,
                    )
                )
                existing = result.first()
                if existing is None:
                    session.add(
                        GraphEdgeTable(
                            edge_type=etype,
                            src_id=src_id,
                            dst_id=dst_id,
                            attrs=attrs,
                            updated_at=now,
                        )
                    )
                else:
                    existing.attrs = {**existing.attrs, **attrs}
                    existing.updated_at = now
                    session.add(existing)
                await session.commit()

    async def delete_graph_edge(self, edge_type: str, src_id: UUID, dst_id: UUID) -> None:
        etype = GraphEdgeType(edge_type)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(GraphEdgeTable).where(
                    col(GraphEdgeTable.edge_type) == etype,
                    col(GraphEdgeTable.src_id) == src_id,
                    col(GraphEdgeTable.dst_id) == dst_id,
                )
            )
            row = result.first()
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def graph_neighbors(
        self,
        node_id: UUID,
        edge_type: str | None = None,
    ) -> list[tuple[UUID, str, dict[str, object]]]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(GraphEdgeTable).where(col(GraphEdgeTable.src_id) == node_id)
            if edge_type is not None:
                stmt = stmt.where(col(GraphEdgeTable.edge_type) == GraphEdgeType(edge_type))
            result = await session.exec(stmt)
            rows = list(result)
        return [(r.dst_id, r.edge_type.value, dict(r.attrs)) for r in rows]

    async def graph_neighbor_edges(
        self,
        node_id: UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Outbound edges from a node as ``GraphEdgeTable`` rows (M9.F1).

        Unlike ``graph_neighbors`` (which flattens to tuples), this returns
        the rows so the typed-edge API projector (``LinkedToEdge.from_domain``
        / ``BelongsToPersonaEdge.from_domain``) can consume them. Ordered by
        id (UUIDv7, creation order) for a stable cursor.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(GraphEdgeTable)
                .where(col(GraphEdgeTable.src_id) == node_id)
                .order_by(col(GraphEdgeTable.id))
                .limit(limit)
                .offset(offset)
            )
            result = await session.exec(stmt)
            return list(result)

    async def count_graph_neighbors(self, node_id: UUID) -> int:
        """Count outbound edges from a node (M9.F1)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(GraphEdgeTable)
                .where(col(GraphEdgeTable.src_id) == node_id)
            )
            result = await session.exec(stmt)
            return int(result.one())

    async def graph_edges_by_type(
        self,
        edge_type: str,
        src_id: UUID | None = None,
        dst_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, dict[str, object]]]:
        etype = GraphEdgeType(edge_type)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(GraphEdgeTable).where(col(GraphEdgeTable.edge_type) == etype)
            if src_id is not None:
                stmt = stmt.where(col(GraphEdgeTable.src_id) == src_id)
            if dst_id is not None:
                stmt = stmt.where(col(GraphEdgeTable.dst_id) == dst_id)
            result = await session.exec(stmt)
            rows = list(result)
        return [(r.src_id, r.dst_id, dict(r.attrs)) for r in rows]

    async def graph_stats(self) -> dict[str, int]:
        actor_key = GraphNodeType.ACTOR.name
        persona_key = GraphNodeType.PERSONA.name
        linked_key = GraphEdgeType.LINKED_TO.name
        belongs_key = GraphEdgeType.BELONGS_TO_PERSONA.name
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            actors = (
                await session.exec(  # type: ignore[call-overload]
                    text("SELECT COUNT(*) FROM graph_node WHERE node_type = :t"),
                    params={"t": actor_key},
                )
            ).scalar_one()
            personas = (
                await session.exec(  # type: ignore[call-overload]
                    text("SELECT COUNT(*) FROM graph_node WHERE node_type = :t"),
                    params={"t": persona_key},
                )
            ).scalar_one()
            linked = (
                await session.exec(  # type: ignore[call-overload]
                    text("SELECT COUNT(*) FROM graph_edge WHERE edge_type = :t"),
                    params={"t": linked_key},
                )
            ).scalar_one()
            persona_edges = (
                await session.exec(  # type: ignore[call-overload]
                    text("SELECT COUNT(*) FROM graph_edge WHERE edge_type = :t"),
                    params={"t": belongs_key},
                )
            ).scalar_one()
        return {
            "actors": int(actors),
            "personas": int(personas),
            "linked_to_edges": int(linked),
            "belongs_to_persona_edges": int(persona_edges),
        }


__all__ = ["GraphMixin"]
