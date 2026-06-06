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

from sqlalchemy import func
from sqlmodel import col, select

from eyenet.contracts.collector import CollectorFleetHealth, CollectorRow, compute_instance_id
from eyenet.contracts.enums import (
    CollectorDesiredState,
    CollectorObservedState,
    SourceKind,
)
from eyenet.models.collector import CollectorTable
from eyenet.models.identity import IdentityTable

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

    async def resolve_collector_by_instance_id(self, instance_id: str) -> CollectorRow | None:
        """Reverse the 8-char bus ``instance_id`` to its collector row (M9.E2).

        ``RawMessageEnvelope.instance_id`` is ``compute_instance_id(identity
        name, kind)`` — a one-way hash not stored on the collector. We recompute
        it from each collector's identity name + kind and match. Small-operator
        scope keeps the fleet tiny, so the linear scan is fine. Returns ``None``
        if no collector matches (the message can't be attributed → skipped).
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CollectorTable, IdentityTable.name).join(
                IdentityTable,
                col(CollectorTable.identity_id) == col(IdentityTable.id),
            )
            result = await session.exec(stmt)
            for collector, identity_name in result:
                if compute_instance_id(identity_name, collector.kind) == instance_id:
                    return _row(collector)
            return None

    async def list_collectors(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CollectorRow]:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CollectorTable).order_by(col(CollectorTable.created_at).asc())
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = await session.exec(stmt)
            return [_row(r) for r in list(result)]

    async def count_collectors(self) -> int:
        """Total collector rows."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(func.count()).select_from(CollectorTable)
            result = await session.exec(stmt)
            return int(result.one())

    async def update_collector(
        self,
        *,
        collector_id: UUID,
        config: dict[str, Any] | None = None,
        instance_name: str | None = None,
        notes: str | None = None,
    ) -> CollectorRow:
        """Operator PATCH of editable metadata (API_PLAN §4.11.2).

        ``None`` means *leave unchanged* (consistent with
        :meth:`record_collector_observed_state`) — so ``notes`` cannot be
        cleared through this path; remove-and-recreate or a dedicated clear
        call would be needed. ``desired_state`` and ``observed_state`` are
        NOT touched here: ``desired_state`` goes through
        :meth:`set_collector_desired_state`, ``observed_state`` is
        supervisor-only. Raises :class:`ValueError` if the collector is
        missing.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(CollectorTable, collector_id)
            if table is None:
                raise ValueError(f"collector {collector_id} not found")
            if config is not None:
                table.config = dict(config)
            if instance_name is not None:
                table.instance_name = instance_name
            if notes is not None:
                table.notes = notes
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _row(table)

    async def collector_fleet_health(self) -> CollectorFleetHealth:
        """Fleet snapshot: counts by observed_state, oldest live heartbeat,
        restart-storm leader (API_PLAN §3.9)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(select(CollectorTable))
            rows = list(result)
            counts: dict[CollectorObservedState, int] = {}
            oldest_heartbeat: datetime | None = None
            leader_id: UUID | None = None
            max_restart = 0
            for r in rows:
                counts[r.observed_state] = counts.get(r.observed_state, 0) + 1
                if (
                    r.observed_state is not CollectorObservedState.STOPPED
                    and r.last_heartbeat_at is not None
                ):
                    hb = _coerce_utc(r.last_heartbeat_at)
                    if hb is not None and (oldest_heartbeat is None or hb < oldest_heartbeat):
                        oldest_heartbeat = hb
                if r.restart_count > max_restart:
                    max_restart = r.restart_count
                    leader_id = r.id
            return CollectorFleetHealth(
                total=len(rows),
                counts_by_observed_state=counts,
                oldest_heartbeat_at=oldest_heartbeat,
                restart_storm_leader_id=leader_id if max_restart > 0 else None,
                max_restart_count=max_restart,
            )

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
