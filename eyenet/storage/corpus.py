"""SQLiteCorpusStore — append + iter_since.

Corpus is a query view over `MessageTable` (PLAN §5.3 says append-only per
actor; we don't materialize a separate row set). The corpus DB file owns
the `CorpusCursorTable` only; the actual messages are in the messages DB.
This means `iter_since` lives on the messages engine — but the cursor
read/write lives on the corpus engine. Service code crosses the boundary
explicitly (PLAN §5.2 boundary list).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from eyenet.contracts.storage import CorpusStore
from eyenet.models import MessageTable


class SQLiteCorpusStore(CorpusStore):
    """Note: this impl reads from the messages engine for `iter_since`.

    The `corpus` engine holds only `CorpusCursorTable`; the cursor read/write
    path is `SQLiteCursorStore` (separate sub-API in M2).
    """

    def __init__(self, messages_engine: Engine) -> None:
        self._engine = messages_engine

    async def append(
        self,
        _actor_id: UUID,
        _ts: datetime,
        _evidence_ref: str,
        _message_length: int,
        _language: str | None,
    ) -> None:
        # Corpus is implicit in MessageTable rows. M2 may introduce an
        # explicit corpus index for performance; for now this is a no-op.
        return None

    async def iter_since(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str]]:
        with Session(self._engine) as session:
            stmt = (
                select(
                    MessageTable.sent_at_source,
                    MessageTable.id,
                    MessageTable.evidence_ref,
                )
                .where(MessageTable.actor_id == actor_id)
                .where(MessageTable.sent_at_source >= since_ts)
                .where(MessageTable.id != since_msg_id)
                .order_by(col(MessageTable.sent_at_source), col(MessageTable.id))
            )
            return [(ts, mid, ref) for ts, mid, ref in session.exec(stmt)]

    async def iter_since_with_reply(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str, UUID | None]]:
        with Session(self._engine) as session:
            stmt = (
                select(
                    MessageTable.sent_at_source,
                    MessageTable.id,
                    MessageTable.evidence_ref,
                    MessageTable.reply_to_msg_id,
                )
                .where(MessageTable.actor_id == actor_id)
                .where(MessageTable.sent_at_source >= since_ts)
                .where(MessageTable.id != since_msg_id)
                .order_by(col(MessageTable.sent_at_source), col(MessageTable.id))
            )
            return [(ts, mid, ref, reply) for ts, mid, ref, reply in session.exec(stmt)]


__all__ = ["SQLiteCorpusStore"]
