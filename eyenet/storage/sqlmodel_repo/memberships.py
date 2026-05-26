# SPDX-License-Identifier: AGPL-3.0-or-later
"""MembershipsMixin — CollectorGroupMembership + MessageObservation (M9.C5).

ANSI SQL only (CLAUDE.md §2.3 Rule 1). ``was_first_sighting`` is determined by
a SELECT-before-INSERT: the first caller for a given message_id sees count=0
and gets True; subsequent callers see count>=1 and get False. Under SQLite's
single-writer serialization this is race-safe. Under Postgres a future override
should use SELECT FOR UPDATE on the MessageObservation table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import null
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from eyenet.contracts.enums import JoinedVia
from eyenet.contracts.membership import CollectorGroupMembershipRow, MessageObservationRow
from eyenet.models.membership import CollectorGroupMembershipTable, MessageObservationTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _membership_row(table: CollectorGroupMembershipTable) -> CollectorGroupMembershipRow:
    data = table.model_dump()
    for k in ("joined_at", "left_at"):
        data[k] = _coerce_utc(data.get(k))
    return CollectorGroupMembershipRow.model_validate(data)


def _obs_row(table: MessageObservationTable) -> MessageObservationRow:
    data = table.model_dump(exclude={"first_sighting_claim"})
    data["observed_at_ingest"] = _coerce_utc(data.get("observed_at_ingest"))
    return MessageObservationRow.model_validate(data)


class MembershipsMixin:
    """CRUD surface for CollectorGroupMembershipTable and MessageObservationTable."""

    async def open_membership(
        self,
        *,
        collector_id: UUID,
        group_id: UUID,
        joined_at: datetime,
        joined_via: JoinedVia,
        joined_via_candidate_id: UUID | None = None,
    ) -> CollectorGroupMembershipRow:
        """Record that a collector joined a group.

        Raises :class:`ValueError` if the collector already has an active
        (``left_at IS NULL``) membership for this group — re-joining after a
        clean departure must call ``close_membership`` first.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            # Guard: reject duplicate active membership.
            existing = await session.exec(
                select(CollectorGroupMembershipTable).where(
                    CollectorGroupMembershipTable.collector_id == collector_id,
                    CollectorGroupMembershipTable.group_id == group_id,
                    col(CollectorGroupMembershipTable.left_at) == null(),
                )
            )
            if existing.one_or_none() is not None:
                raise ValueError(
                    f"collector {collector_id} already has an active membership in group {group_id}"
                )

            row = CollectorGroupMembershipTable(
                collector_id=collector_id,
                group_id=group_id,
                joined_at=joined_at,
                joined_via=joined_via,
                joined_via_candidate_id=joined_via_candidate_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _membership_row(row)

    async def close_membership(
        self,
        *,
        collector_id: UUID,
        group_id: UUID,
        left_at: datetime,
        left_reason: str,
    ) -> CollectorGroupMembershipRow:
        """Mark a membership as departed (``left_at`` + ``left_reason`` set).

        Raises :class:`ValueError` if no active membership exists for this
        (collector, group) pair.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(CollectorGroupMembershipTable).where(
                    CollectorGroupMembershipTable.collector_id == collector_id,
                    CollectorGroupMembershipTable.group_id == group_id,
                    col(CollectorGroupMembershipTable.left_at) == null(),
                )
            )
            row = result.one_or_none()
            if row is None:
                raise ValueError(
                    f"no active membership for collector {collector_id} in group {group_id}"
                )
            row.left_at = left_at
            row.left_reason = left_reason
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _membership_row(row)

    async def list_active_memberships(
        self,
        *,
        collector_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> list[CollectorGroupMembershipRow]:
        """Return active memberships (``left_at IS NULL``).

        Filter by ``collector_id`` to answer "what is this collector in?"
        Filter by ``group_id`` to answer "who is currently in this group?"
        Omit both to return all active memberships.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(CollectorGroupMembershipTable).where(
                col(CollectorGroupMembershipTable.left_at) == null(),
            )
            if collector_id is not None:
                stmt = stmt.where(CollectorGroupMembershipTable.collector_id == collector_id)
            if group_id is not None:
                stmt = stmt.where(CollectorGroupMembershipTable.group_id == group_id)
            stmt = stmt.order_by(col(CollectorGroupMembershipTable.joined_at).asc())
            result = await session.exec(stmt)
            return [_membership_row(r) for r in list(result)]

    async def record_observation(
        self,
        *,
        message_id: UUID,
        collector_id: UUID,
        observed_at_ingest: datetime,
    ) -> MessageObservationRow:
        """Record that a collector observed a message; set was_first_sighting atomically.

        ``was_first_sighting`` is True iff this is the first call for this
        ``message_id``. The claim is made atomically via the generated column
        ``first_sighting_claim`` + UNIQUE constraint: the INSERT with
        ``was_first_sighting=True`` either succeeds (this caller wins) or
        raises IntegrityError (another caller beat it), in which case we
        retry with ``False``.

        Idempotent on ``(message_id, collector_id)`` — a second call for the
        same pair returns the existing row without changing was_first_sighting.
        """
        # Idempotency guard: return existing row if this pair already exists.
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.exec(
                select(MessageObservationTable).where(
                    MessageObservationTable.message_id == message_id,
                    MessageObservationTable.collector_id == collector_id,
                )
            )
            extant = existing.one_or_none()
            if extant is not None:
                return _obs_row(extant)

        # Atomic first-sighting claim via INSERT + UNIQUE on first_sighting_claim.
        # We skip session.refresh() because the generated column is the only
        # DB-side value and we never expose it; everything else is caller-set.
        # Under concurrent asyncio.gather + StaticPool, refresh() can race with
        # the other coroutine's rollback and produce a spurious refresh error.
        try:
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                row = MessageObservationTable(
                    message_id=message_id,
                    collector_id=collector_id,
                    observed_at_ingest=observed_at_ingest,
                    was_first_sighting=True,
                )
                session.add(row)
                await session.commit()
            return MessageObservationRow(
                message_id=message_id,
                collector_id=collector_id,
                observed_at_ingest=observed_at_ingest,
                was_first_sighting=True,
            )
        except IntegrityError:
            # Another caller won the first-sighting claim — insert as secondary.
            # Avoid session.refresh() after IntegrityError-rollback on StaticPool;
            # we know all field values so build the row contract directly.
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                row = MessageObservationTable(
                    message_id=message_id,
                    collector_id=collector_id,
                    observed_at_ingest=observed_at_ingest,
                    was_first_sighting=False,
                )
                session.add(row)
                await session.commit()
            return MessageObservationRow(
                message_id=message_id,
                collector_id=collector_id,
                observed_at_ingest=observed_at_ingest,
                was_first_sighting=False,
            )


__all__ = ["MembershipsMixin"]
