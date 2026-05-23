"""SQLiteCursorStore — per-primitive CorpusCursor read/write.

Composite PK `(actor_id, primitive_name)` per MODELS §2.16. Lives in the
corpus DB file (`corpus.db`). Cross-store reference to actor (in messages.db)
is a plain UUID with no FK — intentional per PLAN §5.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from eyenet.models import CorpusCursorTable

# Sentinel: the epoch beginning — "no messages processed yet".
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")


class SQLiteCursorStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, actor_id: UUID, primitive_name: str) -> tuple[datetime, UUID]:
        """Return `(last_processed_msg_ts, last_processed_msg_id)` or epoch sentinels."""

        with Session(self._engine) as session:
            row = session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    CorpusCursorTable.primitive_name == primitive_name,
                )
            ).first()
            if row is None:
                return _EPOCH, _NULL_UUID
            return row.last_processed_msg_ts, row.last_processed_msg_id

    def set(
        self,
        actor_id: UUID,
        primitive_name: str,
        last_ts: datetime,
        last_msg_id: UUID,
    ) -> None:
        """Upsert the cursor for `(actor_id, primitive_name)`."""

        with Session(self._engine) as session:
            row = session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    CorpusCursorTable.primitive_name == primitive_name,
                )
            ).first()
            if row is None:
                session.add(
                    CorpusCursorTable(
                        actor_id=actor_id,
                        primitive_name=primitive_name,
                        last_processed_msg_ts=last_ts,
                        last_processed_msg_id=last_msg_id,
                    )
                )
            else:
                row.last_processed_msg_ts = last_ts
                row.last_processed_msg_id = last_msg_id
                session.add(row)
            session.commit()


__all__ = ["SQLiteCursorStore"]
