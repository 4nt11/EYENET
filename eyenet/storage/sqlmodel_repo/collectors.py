# SPDX-License-Identifier: AGPL-3.0-or-later
"""CollectorsMixin — persisted collector CRUD + state writes (API_PLAN §4.11).

ANSI SQL only (CLAUDE.md §2.3 Rule 1). No dialect-specific imports, no
``ON CONFLICT``, no triggers. Identity uniqueness is enforced by the
column-level ``unique`` constraint on ``Collector.identity_id``; the
duplicate-collector test relies on the database raising
:class:`IntegrityError` rather than the mixin pre-checking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlmodel import col, select

from eyenet.contracts.collector import CollectorRow
from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    SourceKind,
)
from eyenet.models.collector import CollectorTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _row(table: CollectorTable) -> CollectorRow:
    data = table.model_dump()
    for k in ("created_at", "last_heartbeat_at"):
        data[k] = _coerce_utc(data.get(k))
    return CollectorRow.model_validate(data)


class CollectorsMixin:
    """CRUD + state-write surface for ``CollectorTable`` rows."""

    async def create_collector(
        self,
        *,
        instance_name: str,
        kind: SourceKind,
        source_id: UUID,
        identity_id: UUID,
        config: dict[str, Any],
        created_at: datetime,
        created_by_user_id: UUID,
        notes: str | None = None,
    ) -> CollectorRow:
        table = CollectorTable(
            instance_name=instance_name,
            kind=kind,
            source_id=source_id,
            identity_id=identity_id,
            config=dict(config),
            desired_state=CollectorDesiredState.STOPPED,
            observed_state=CollectorObservedState.STOPPED,
            restart_count=0,
            created_at=created_at,
            created_by_user_id=created_by_user_id,
            notes=notes,
        )
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def get_collector(self, collector_id: UUID) -> CollectorRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CollectorTable, collector_id)
            return _row(table) if table is not None else None

    async def list_collectors(self) -> list[CollectorRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CollectorTable).order_by(col(CollectorTable.created_at).asc())
            result = await session.exec(stmt)
            return [_row(r) for r in list(result)]

    async def set_collector_desired_state(
        self,
        *,
        collector_id: UUID,
        desired_state: CollectorDesiredState,
    ) -> CollectorRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CollectorTable, collector_id)
            if table is None:
                raise ValueError(f"collector {collector_id} not found")
            table.desired_state = desired_state
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def record_collector_observed_state(
        self,
        *,
        collector_id: UUID,
        observed_state: CollectorObservedState,
        last_heartbeat_at: datetime | None = None,
        last_error_type: str | None = None,
        last_error_message: str | None = None,
        restart_count: int | None = None,
    ) -> CollectorRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CollectorTable, collector_id)
            if table is None:
                raise ValueError(f"collector {collector_id} not found")
            table.observed_state = observed_state
            if last_heartbeat_at is not None:
                table.last_heartbeat_at = last_heartbeat_at
            if restart_count is not None:
                table.restart_count = restart_count
            # last_error fields are written as a pair (CHECK at the
            # SQL layer enforces both-NULL-or-both-set, so partial
            # updates would fail at commit). Treat any explicit call
            # as "set them to whatever pair the caller passed".
            if observed_state is CollectorObservedState.CRASHED:
                if last_error_type is None or last_error_message is None:
                    raise ValueError(
                        "CRASHED transition requires both last_error_type and last_error_message",
                    )
                table.last_error_type = last_error_type
                table.last_error_message = last_error_message
            elif last_error_type is not None or last_error_message is not None:
                # Caller explicitly passed an error pair on a non-CRASHED
                # transition — accept it (could be reporting a transient
                # error during STARTING) but require both values.
                if last_error_type is None or last_error_message is None:
                    raise ValueError(
                        "last_error_type and last_error_message must be set together",
                    )
                table.last_error_type = last_error_type
                table.last_error_message = last_error_message
            else:
                # No error info supplied AND not crashing — clear stale
                # error breadcrumbs from a previous crash so the row
                # doesn't carry forward a misleading message.
                table.last_error_type = None
                table.last_error_message = None
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def delete_collector(self, collector_id: UUID) -> None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CollectorTable, collector_id)
            if table is None:
                raise ValueError(f"collector {collector_id} not found")
            await session.delete(table)
            await session.commit()


__all__ = ["CollectorsMixin"]
