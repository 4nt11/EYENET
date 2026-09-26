# SPDX-License-Identifier: AGPL-3.0-or-later
"""IncidentsMixin — append-only incident classification results.

Generic SQLModel ORM only (no dialect-specific SQL): the table is append-only so the
bulk writer is a plain ANSI insert; no ON CONFLICT / upsert is needed. See
eyenet/models/incident.py and CLAUDE.md §2.3 (Rule 1: no dialect leak in mixins).
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.incident import IncidentRow
from eyenet.models import IncidentTable

from ._helpers import safe_session


class IncidentsMixin:
    async def put_incidents_bulk(self, incident_rows: list[object]) -> None:
        """Persist many IncidentRows in ONE session — the classifier service's batch
        flush. Append-only; amortizes async-session overhead across the batch."""
        if not incident_rows:
            return
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            for r in incident_rows:
                row = cast("IncidentRow", r)
                session.add(IncidentTable(**row.model_dump()))
            await session.commit()

    async def incidents_for_message(self, message_id: UUID, limit: int = 10) -> list[object]:
        """Classification history for one message, latest run first."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IncidentTable)
                .where(IncidentTable.message_id == message_id)
                .order_by(col(IncidentTable.classified_at).desc())
                .limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())

    async def recent_incidents(self, limit: int = 50) -> list[object]:
        """Most recently classified incidents (operator triage feed backing query)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IncidentTable).order_by(col(IncidentTable.classified_at).desc()).limit(limit)
            )
            result = await session.exec(stmt)
            return list(result.all())
