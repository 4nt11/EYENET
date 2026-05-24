"""SQLiteGraphStore — typed SQLModel-backed graph store.

Node schema: GraphNodeTable (node_id + node_type + attrs JSON).
Edge schema: GraphEdgeTable (edge_type + src_id + dst_id + attrs JSON).

Unique node key: (node_id, node_type). Two nodes of different types can share
a UUID — that's intentional (an Actor and a Persona can theoretically have the
same ID without collision because they're different types).

Edges have a (edge_type, src_id, dst_id) natural key enforced at upsert time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from opentelemetry import trace
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

import eyenet.models  # noqa: F401 — registers all tables on SQLModel.metadata
from eyenet.contracts.storage import GraphStore
from eyenet.models.graph import GraphEdgeTable, GraphEdgeType, GraphNodeTable, GraphNodeType
from eyenet.storage.engines import StoreName, create_all_for

_tracer = trace.get_tracer("eyenet.storage.graph")


class SQLiteGraphStore(GraphStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        create_all_for(StoreName.MAIN, engine)

    async def upsert_node(
        self,
        node_type: str,
        node_id: UUID,
        attrs: dict[str, object],
    ) -> None:
        now = datetime.now(tz=UTC)
        ntype = GraphNodeType(node_type)
        with (
            _tracer.start_as_current_span(
                "storage.graph.upsert_node",
                attributes={
                    "graph.node_type": ntype.value,
                    "graph.node_id": str(node_id),
                },
            ),
            Session(self._engine) as session,
        ):
            existing = session.exec(
                select(GraphNodeTable).where(
                    col(GraphNodeTable.node_id) == node_id,
                    col(GraphNodeTable.node_type) == ntype,
                )
            ).first()
            if existing is None:
                session.add(
                    GraphNodeTable(node_id=node_id, node_type=ntype, attrs=attrs, updated_at=now)
                )
            else:
                existing.attrs = {**existing.attrs, **attrs}
                existing.updated_at = now
                session.add(existing)
            session.commit()

    async def upsert_edge(
        self,
        edge_type: str,
        src_id: UUID,
        dst_id: UUID,
        attrs: dict[str, object],
    ) -> None:
        now = datetime.now(tz=UTC)
        etype = GraphEdgeType(edge_type)
        with (
            _tracer.start_as_current_span(
                "storage.graph.upsert_edge",
                attributes={
                    "graph.edge_type": etype.value,
                    "graph.src_id": str(src_id),
                    "graph.dst_id": str(dst_id),
                },
            ),
            Session(self._engine) as session,
        ):
            existing = session.exec(
                select(GraphEdgeTable).where(
                    col(GraphEdgeTable.edge_type) == etype,
                    col(GraphEdgeTable.src_id) == src_id,
                    col(GraphEdgeTable.dst_id) == dst_id,
                )
            ).first()
            if existing is None:
                session.add(
                    GraphEdgeTable(
                        edge_type=etype, src_id=src_id, dst_id=dst_id, attrs=attrs, updated_at=now
                    )
                )
            else:
                existing.attrs = {**existing.attrs, **attrs}
                existing.updated_at = now
                session.add(existing)
            session.commit()

    async def delete_edge(self, edge_type: str, src_id: UUID, dst_id: UUID) -> None:
        etype = GraphEdgeType(edge_type)
        with Session(self._engine) as session:
            row = session.exec(
                select(GraphEdgeTable).where(
                    col(GraphEdgeTable.edge_type) == etype,
                    col(GraphEdgeTable.src_id) == src_id,
                    col(GraphEdgeTable.dst_id) == dst_id,
                )
            ).first()
            if row is not None:
                session.delete(row)
                session.commit()

    async def neighbors(
        self,
        node_id: UUID,
        edge_type: str | None = None,
    ) -> list[tuple[UUID, str, dict[str, object]]]:
        with Session(self._engine) as session:
            stmt = select(GraphEdgeTable).where(col(GraphEdgeTable.src_id) == node_id)
            if edge_type is not None:
                stmt = stmt.where(col(GraphEdgeTable.edge_type) == GraphEdgeType(edge_type))
            rows = session.exec(stmt).all()
        return [(r.dst_id, r.edge_type.value, dict(r.attrs)) for r in rows]

    async def edges_by_type(
        self,
        edge_type: str,
        src_id: UUID | None = None,
        dst_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, dict[str, object]]]:
        etype = GraphEdgeType(edge_type)
        with Session(self._engine) as session:
            stmt = select(GraphEdgeTable).where(col(GraphEdgeTable.edge_type) == etype)
            if src_id is not None:
                stmt = stmt.where(col(GraphEdgeTable.src_id) == src_id)
            if dst_id is not None:
                stmt = stmt.where(col(GraphEdgeTable.dst_id) == dst_id)
            rows = session.exec(stmt).all()
        return [(r.src_id, r.dst_id, dict(r.attrs)) for r in rows]

    async def stats(self) -> dict[str, int]:
        # SQLModel stores StrEnum by name (e.g. "ACTOR"), not by value ("actor").
        actor_key = GraphNodeType.ACTOR.name
        persona_key = GraphNodeType.PERSONA.name
        linked_key = GraphEdgeType.LINKED_TO.name
        belongs_key = GraphEdgeType.BELONGS_TO_PERSONA.name
        with self._engine.connect() as conn:
            actors = conn.execute(
                text("SELECT COUNT(*) FROM graph_node WHERE node_type = :t"),
                {"t": actor_key},
            ).scalar_one()
            personas = conn.execute(
                text("SELECT COUNT(*) FROM graph_node WHERE node_type = :t"),
                {"t": persona_key},
            ).scalar_one()
            linked = conn.execute(
                text("SELECT COUNT(*) FROM graph_edge WHERE edge_type = :t"),
                {"t": linked_key},
            ).scalar_one()
            persona_edges = conn.execute(
                text("SELECT COUNT(*) FROM graph_edge WHERE edge_type = :t"),
                {"t": belongs_key},
            ).scalar_one()
        return {
            "actors": int(actors),
            "personas": int(personas),
            "linked_to_edges": int(linked),
            "belongs_to_persona_edges": int(persona_edges),
        }

    def _get_node(self, session: Session, node_type: str, node_id: UUID) -> GraphNodeTable | None:
        return session.exec(
            select(GraphNodeTable).where(
                col(GraphNodeTable.node_id) == node_id,
                col(GraphNodeTable.node_type) == GraphNodeType(node_type),
            )
        ).first()

    def _get_attrs(self, session: Session, node_type: str, node_id: UUID) -> dict[str, Any]:
        row = self._get_node(session, node_type, node_id)
        return dict(row.attrs) if row is not None else {}


__all__ = ["SQLiteGraphStore"]
