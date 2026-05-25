# SPDX-License-Identifier: AGPL-3.0-or-later
"""CursorsMixin — per-primitive corpus-cursor read/write (MODELS §2.16)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import col, select

from eyenet.models import CorpusCursorTable

from ._helpers import safe_session

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")


class CursorsMixin:
    async def get_cursors_bulk(
        self,
        actor_id: UUID,
        primitive_names: Sequence[str],
    ) -> dict[str, tuple[datetime, UUID]]:
        """Read every (actor, primitive) cursor in one round-trip.

        Missing rows fall back to (_EPOCH, _NULL_UUID) — the same sentinel
        ``get_cursor`` returns. Used by the StylometricSensor dispatch loop
        to amortize per-primitive session overhead.
        """
        if not primitive_names:
            return {}
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    col(CorpusCursorTable.primitive_name).in_(list(primitive_names)),
                )
            )
            rows = list(result.all())
        out: dict[str, tuple[datetime, UUID]] = dict.fromkeys(primitive_names, (_EPOCH, _NULL_UUID))
        for r in rows:
            out[r.primitive_name] = (r.last_processed_msg_ts, r.last_processed_msg_id)
        return out

    async def get_cursor(
        self,
        actor_id: UUID,
        primitive_name: str,
    ) -> tuple[datetime, UUID]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    CorpusCursorTable.primitive_name == primitive_name,
                )
            )
            row = result.first()
            if row is None:
                return _EPOCH, _NULL_UUID
            return row.last_processed_msg_ts, row.last_processed_msg_id

    async def set_cursors_bulk(
        self,
        actor_id: UUID,
        updates: Sequence[tuple[str, datetime, UUID]],
    ) -> None:
        """Upsert many cursor rows in one session. Race-safe across
        concurrent dispatches for the same actor.

        Generic SELECT-then-add path. Concurrent writers can collide on
        the (actor_id, primitive_name) UNIQUE — backends that need a
        dialect-specific upsert (SQLite ``ON CONFLICT``, Postgres
        ``ON CONFLICT``, MySQL ``ON DUPLICATE KEY``) override this method
        in the concrete repository.
        """
        if not updates:
            return
        names = [u[0] for u in updates]
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    col(CorpusCursorTable.primitive_name).in_(names),
                )
            )
            existing = {r.primitive_name: r for r in result.all()}
            for name, last_ts, last_msg_id in updates:
                row = existing.get(name)
                if row is None:
                    session.add(
                        CorpusCursorTable(
                            actor_id=actor_id,
                            primitive_name=name,
                            last_processed_msg_ts=last_ts,
                            last_processed_msg_id=last_msg_id,
                        )
                    )
                else:
                    row.last_processed_msg_ts = last_ts
                    row.last_processed_msg_id = last_msg_id
                    session.add(row)
            await session.commit()

    async def set_cursor(
        self,
        actor_id: UUID,
        primitive_name: str,
        last_ts: datetime,
        last_msg_id: UUID,
    ) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(CorpusCursorTable).where(
                    CorpusCursorTable.actor_id == actor_id,
                    CorpusCursorTable.primitive_name == primitive_name,
                )
            )
            row = result.first()
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
            await session.commit()


__all__ = ["CursorsMixin"]
