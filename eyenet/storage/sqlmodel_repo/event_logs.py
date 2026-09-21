# SPDX-License-Identifier: AGPL-3.0-or-later
"""EventLogsMixin — per-transition event logs (API_PLAN §11.5, MODELS §2.29).

One durable row per state-transition event, the storage-side dual of the bus
envelope. Written by the *producer* of the event — for operator actions that is
the API's durable write sequence (§10.3: audit gate → event-log append → async
publish). Group H's ``StreamReplaySource`` replays these ordered by
``(ts, event_seq)`` with the delivery span parented from ``traceparent``.

Generic (ANSI) — no dialect-specific SQL. ``event_seq`` is allocated
``MAX(event_seq)+1`` per parent under the write lock; the composite
``(parent_id, event_seq)`` PK is the race backstop and a lost race retries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from eyenet.contracts.event_log import EventLogRow
from eyenet.models.event_logs import (
    IdentityEventLogTable,
    LinkageEventLogTable,
    PersonaEventLogTable,
)

from ._helpers import safe_session

# ponytail: MAX+1 under SQLite's write serialization + UNIQUE PK backstop; if a
# future multi-writer backend shows real contention, move to a per-parent
# sequence table. Bounded retry covers the rare lost race.
_SEQ_RETRIES = 5


class EventLogsMixin:
    async def _append_event(
        self,
        *,
        table: type,
        parent_attr: str,
        parent_id: UUID,
        event_subject: str,
        event_id: UUID,
        traceparent: str,
        tracestate: str | None,
        actor: str | None,
        payload_digest: str | None,
        ts: datetime | None,
    ) -> EventLogRow:
        stamp = ts or datetime.now(tz=UTC)
        parent_col = getattr(table, parent_attr)
        last_error: Exception | None = None
        for _ in range(_SEQ_RETRIES):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                max_result = await session.exec(
                    select(func.max(col(table.event_seq))).where(col(parent_col) == parent_id)  # type: ignore[attr-defined]
                )
                next_seq = int(max_result.one() or 0) + 1
                kwargs: dict[str, Any] = {
                    parent_attr: parent_id,
                    "event_seq": next_seq,
                    "event_subject": event_subject,
                    "event_id": event_id,
                    "ts": stamp,
                    "traceparent": traceparent,
                    "tracestate": tracestate,
                    "actor": actor,
                    "payload_digest": payload_digest,
                }
                session.add(table(**kwargs))
                try:
                    await session.commit()
                except IntegrityError as exc:  # lost the event_seq race — retry
                    last_error = exc
                    await session.rollback()
                    continue
                return EventLogRow(
                    parent_id=parent_id,
                    event_seq=next_seq,
                    event_subject=event_subject,
                    event_id=event_id,
                    ts=stamp,
                    traceparent=traceparent,
                    tracestate=tracestate,
                    actor=actor,
                    payload_digest=payload_digest,
                )
        raise RuntimeError(
            f"event_seq allocation for {table.__name__} parent={parent_id} "
            f"failed after {_SEQ_RETRIES} retries"
        ) from last_error

    async def append_linkage_event(
        self,
        *,
        linkage_id: UUID,
        event_subject: str,
        event_id: UUID,
        traceparent: str,
        tracestate: str | None = None,
        actor: str | None = None,
        payload_digest: str | None = None,
        ts: datetime | None = None,
    ) -> EventLogRow:
        return await self._append_event(
            table=LinkageEventLogTable,
            parent_attr="linkage_id",
            parent_id=linkage_id,
            event_subject=event_subject,
            event_id=event_id,
            traceparent=traceparent,
            tracestate=tracestate,
            actor=actor,
            payload_digest=payload_digest,
            ts=ts,
        )

    async def append_persona_event(
        self,
        *,
        persona_id: UUID,
        event_subject: str,
        event_id: UUID,
        traceparent: str,
        tracestate: str | None = None,
        actor: str | None = None,
        payload_digest: str | None = None,
        ts: datetime | None = None,
    ) -> EventLogRow:
        return await self._append_event(
            table=PersonaEventLogTable,
            parent_attr="persona_id",
            parent_id=persona_id,
            event_subject=event_subject,
            event_id=event_id,
            traceparent=traceparent,
            tracestate=tracestate,
            actor=actor,
            payload_digest=payload_digest,
            ts=ts,
        )

    async def append_identity_event(
        self,
        *,
        identity_id: UUID,
        event_subject: str,
        event_id: UUID,
        traceparent: str,
        tracestate: str | None = None,
        actor: str | None = None,
        payload_digest: str | None = None,
        ts: datetime | None = None,
    ) -> EventLogRow:
        return await self._append_event(
            table=IdentityEventLogTable,
            parent_attr="identity_id",
            parent_id=identity_id,
            event_subject=event_subject,
            event_id=event_id,
            traceparent=traceparent,
            tracestate=tracestate,
            actor=actor,
            payload_digest=payload_digest,
            ts=ts,
        )

    async def linkage_events(self, linkage_id: UUID) -> list[EventLogRow]:
        """Replay-ordered events for one linkage (Group H uses this)."""
        return await self._events_for(LinkageEventLogTable, "linkage_id", linkage_id)

    async def persona_events(self, persona_id: UUID) -> list[EventLogRow]:
        return await self._events_for(PersonaEventLogTable, "persona_id", persona_id)

    async def identity_events(self, identity_id: UUID) -> list[EventLogRow]:
        return await self._events_for(IdentityEventLogTable, "identity_id", identity_id)

    async def linkage_events_since(
        self, after_event_id: UUID | None, limit: int
    ) -> list[EventLogRow]:
        return await self._events_since(LinkageEventLogTable, "linkage_id", after_event_id, limit)

    async def persona_events_since(
        self, after_event_id: UUID | None, limit: int
    ) -> list[EventLogRow]:
        return await self._events_since(PersonaEventLogTable, "persona_id", after_event_id, limit)

    async def identity_events_since(
        self, after_event_id: UUID | None, limit: int
    ) -> list[EventLogRow]:
        return await self._events_since(IdentityEventLogTable, "identity_id", after_event_id, limit)

    async def _events_for(
        self, table: type, parent_attr: str, parent_id: UUID
    ) -> list[EventLogRow]:
        parent_col = getattr(table, parent_attr)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result: Any = await session.exec(
                select(table)
                .where(col(parent_col) == parent_id)
                .order_by(col(table.ts))  # type: ignore[attr-defined]
                .order_by(col(table.event_seq))  # type: ignore[attr-defined]
            )
            rows = list(result)
        return [_to_row(r, parent_attr) for r in rows]

    async def _events_since(
        self, table: type, parent_attr: str, after_event_id: UUID | None, limit: int
    ) -> list[EventLogRow]:
        # Global event_id cursor (uuid7 = time-ordered, fixed-width): ``> after``
        # is a chronological cross-parent scan. Generic ANSI — no dialect leak.
        stmt: Any = select(table).order_by(col(table.event_id))  # type: ignore[attr-defined]
        if after_event_id is not None:
            stmt = stmt.where(col(table.event_id) > after_event_id)  # type: ignore[attr-defined]
        stmt = stmt.limit(limit)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result: Any = await session.exec(stmt)
            rows = list(result)
        return [_to_row(r, parent_attr) for r in rows]


def _to_row(r: Any, parent_attr: str) -> EventLogRow:
    return EventLogRow(
        parent_id=getattr(r, parent_attr),
        event_seq=r.event_seq,
        event_subject=r.event_subject,
        event_id=r.event_id,
        ts=r.ts.replace(tzinfo=UTC) if r.ts.tzinfo is None else r.ts,
        traceparent=r.traceparent,
        tracestate=r.tracestate,
        actor=r.actor,
        payload_digest=r.payload_digest,
    )


__all__ = ["EventLogsMixin"]
