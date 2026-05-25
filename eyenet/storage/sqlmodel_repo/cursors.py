# SPDX-License-Identifier: AGPL-3.0-or-later
"""CursorsMixin — per-primitive corpus-cursor read/write (MODELS §2.16)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import select

from eyenet.models import CorpusCursorTable

from ._helpers import safe_session

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NULL_UUID = UUID("00000000-0000-0000-0000-000000000000")


class CursorsMixin:
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
