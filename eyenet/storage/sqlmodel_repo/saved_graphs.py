# SPDX-License-Identifier: AGPL-3.0-or-later
"""SavedGraphsMixin — CRUD for investigation_graph + its node placements.

A saved graph is a named set of node placements (operator edges live in the global
asserted_edge store, not here). ``replace_investigation_graph_nodes`` is the
save-the-canvas operation: delete the graph's placements and re-insert the current
set in one transaction.

Generic SQLModel ORM only (no dialect leak — [[feedback_no_dialect_leak_in_mixins]]).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlmodel import col, delete, select

from eyenet.contracts.investigation_graph import (
    InvestigationGraphNodeRow,
    InvestigationGraphRow,
)
from eyenet.models.investigation_graph import (
    InvestigationGraphNodeTable,
    InvestigationGraphTable,
)

from ._helpers import safe_session

# One node placement: (entity_type, entity_id, x, y, pinned, enrichments_run).
NodePlacement = tuple[str, UUID, float, float, bool, list[str]]


class SavedGraphsMixin:
    async def create_investigation_graph(
        self,
        *,
        name: str,
        description: str | None,
        created_by_user_id: UUID,
        now: datetime | None = None,
    ) -> UUID:
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = InvestigationGraphTable(
                name=name,
                description=description,
                created_by_user_id=created_by_user_id,
                created_at=at,
                updated_at=at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.id

    async def get_investigation_graph(self, graph_id: UUID) -> InvestigationGraphRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(InvestigationGraphTable, graph_id)
            if row is None:
                return None
            return InvestigationGraphRow.model_validate(row.model_dump())

    async def list_investigation_graphs(
        self,
        *,
        created_by_user_id: UUID,
        limit: int,
        offset: int = 0,
    ) -> list[InvestigationGraphRow]:
        """The operator's saved graphs, most-recently-updated first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(InvestigationGraphTable)
                .where(InvestigationGraphTable.created_by_user_id == created_by_user_id)
                .order_by(col(InvestigationGraphTable.updated_at).desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.exec(stmt)
            return [InvestigationGraphRow.model_validate(r.model_dump()) for r in result]

    async def update_investigation_graph(
        self,
        graph_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Rename / re-describe a graph. Only non-None fields are applied. Returns
        False if the graph does not exist."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(InvestigationGraphTable, graph_id)
            if row is None:
                return False
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            row.updated_at = now or datetime.now(tz=UTC)
            session.add(row)
            await session.commit()
            return True

    async def delete_investigation_graph(self, graph_id: UUID) -> bool:
        """Delete a graph and its node placements. Returns False if absent."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(InvestigationGraphTable, graph_id)
            if row is None:
                return False
            await session.exec(
                delete(InvestigationGraphNodeTable).where(
                    col(InvestigationGraphNodeTable.graph_id) == graph_id
                )
            )
            await session.delete(row)
            await session.commit()
            return True

    async def get_investigation_graph_nodes(
        self, graph_id: UUID
    ) -> list[InvestigationGraphNodeRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(InvestigationGraphNodeTable).where(
                    InvestigationGraphNodeTable.graph_id == graph_id
                )
            )
            return [InvestigationGraphNodeRow.model_validate(r.model_dump()) for r in result]

    async def replace_investigation_graph_nodes(
        self,
        graph_id: UUID,
        nodes: list[NodePlacement],
        *,
        edges: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> int:
        """Save-the-canvas: replace the graph's node placements with ``nodes`` and its
        edge list with ``edges`` (when given) in one transaction. Returns the number
        of placements stored. Also bumps the graph's ``updated_at``."""
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(
                delete(InvestigationGraphNodeTable).where(
                    col(InvestigationGraphNodeTable.graph_id) == graph_id
                )
            )
            for entity_type, entity_id, x, y, pinned, enrichments_run in nodes:
                session.add(
                    InvestigationGraphNodeTable(
                        graph_id=graph_id,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        x=x,
                        y=y,
                        pinned=pinned,
                        enrichments_run=enrichments_run,
                        added_at=at,
                    )
                )
            graph = await session.get(InvestigationGraphTable, graph_id)
            if graph is not None:
                if edges is not None:
                    graph.edges = edges
                graph.updated_at = at
                session.add(graph)
            await session.commit()
            return len(nodes)


__all__ = ["SavedGraphsMixin"]
