# SPDX-License-Identifier: AGPL-3.0-or-later
"""CorpusMixin — append + iter_since views over MessageTable."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.models import MessageTable

from ._helpers import safe_session


class CorpusMixin:
    async def append_corpus(
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

    async def iter_corpus_since(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str]]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
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
            result = await session.exec(stmt)
            return [(ts, mid, ref) for ts, mid, ref in result]

    async def iter_corpus_since_with_reply(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str, UUID | None]]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
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
            result = await session.exec(stmt)
            return [(ts, mid, ref, reply) for ts, mid, ref, reply in result]


__all__ = ["CorpusMixin"]
