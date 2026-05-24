"""SQLiteObservationStore — put + latest."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from opentelemetry import trace
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from eyenet.contracts.observation import ObservationRow
from eyenet.contracts.storage import ObservationStore
from eyenet.models import ObservationTable

_tracer = trace.get_tracer("eyenet.storage.observations")


class SQLiteObservationStore(ObservationStore):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    async def put(self, observation_row: object) -> None:
        row = cast("ObservationRow", observation_row)
        table = ObservationTable(**row.model_dump())
        with Session(self._engine) as session:
            session.add(table)
            session.commit()

    async def latest(
        self,
        actor_id: UUID,
        primitive_name: str,
        limit: int = 1,
    ) -> list[object]:
        with Session(self._engine) as session:
            stmt = (
                select(ObservationTable)
                .where(ObservationTable.actor_id == actor_id)
                .where(ObservationTable.primitive_name == primitive_name)
                .order_by(col(ObservationTable.observed_at).desc())
                .limit(limit)
            )
            return list(session.exec(stmt))  # type: ignore[arg-type]

    async def by_evidence_and_primitive(
        self,
        evidence_ref: str,
        primitive_name: str,
    ) -> object | None:
        with (
            _tracer.start_as_current_span(
                "storage.observations.by_evidence",
                attributes={
                    "message.evidence_ref": evidence_ref,
                    "primitive.name": primitive_name,
                },
            ) as by_evidence_span,
            Session(self._engine) as session,
        ):
            row = session.exec(
                select(ObservationTable)
                .where(ObservationTable.evidence_ref == evidence_ref)
                .where(ObservationTable.primitive_name == primitive_name)
                .order_by(col(ObservationTable.observed_at).desc())
            ).first()
            by_evidence_span.set_attribute("result.found", row is not None)
            return row


__all__ = ["SQLiteObservationStore"]
