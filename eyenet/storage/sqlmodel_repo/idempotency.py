# SPDX-License-Identifier: AGPL-3.0-or-later
"""IdempotencyMixin — cross-worker write replay guard (API_PLAN §6/§10.3).

**Reserve-first** semantics: a first-time key is inserted as a ``pending``
reservation *before* the handler runs, so two concurrent identical POSTs cannot
both fire bus events (invariant #6 forbids re-emitting). The winner runs the
handler and finalizes the row with the response; a loser either replays the
finalized response or gets a 409 while the winner is still in flight.

Generic (ANSI): the reservation race is resolved via the ``key`` PK + a caught
``IntegrityError`` — no dialect-specific ``ON CONFLICT`` needed, so no concrete
backend override is required (unlike the audit ``BEGIN IMMEDIATE`` path).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from eyenet.contracts.idempotency import IdempotencyRecordRow, ReserveResult
from eyenet.models.idempotency import IdempotencyRecordTable

from ._helpers import safe_session


def _to_row(r: IdempotencyRecordTable) -> IdempotencyRecordRow:
    return IdempotencyRecordRow(
        key=r.key,
        request_hash=r.request_hash,
        response_status=r.response_status,
        response_body=dict(r.response_body) if r.response_body is not None else None,
        bus_state=r.bus_state,
        system_user_id=r.system_user_id,
        created_at=r.created_at,
        expires_at=r.expires_at,
    )


class IdempotencyMixin:
    async def get_idempotency_record(
        self, key: str, *, now: datetime | None = None
    ) -> IdempotencyRecordRow | None:
        """Return the live record for ``key``, or None if absent/expired."""
        stamp = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(IdempotencyRecordTable, key)
            if row is None:
                return None
            if _expired(row.expires_at, stamp):
                return None
            return _to_row(row)

    async def reserve_idempotency_record(
        self,
        *,
        key: str,
        request_hash: str,
        system_user_id: UUID | None,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> ReserveResult:
        """Insert a ``pending`` reservation. Winner → won=True; otherwise the
        existing (possibly finalized) row is returned. An expired row is
        reclaimed (deleted then re-inserted)."""
        stamp = now or datetime.now(tz=UTC)
        expires_at = stamp + timedelta(seconds=ttl_seconds)
        # Two attempts: the second only runs if we reclaimed an expired row.
        for _ in range(2):
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                session.add(
                    IdempotencyRecordTable(
                        key=key,
                        request_hash=request_hash,
                        response_status=None,
                        response_body=None,
                        bus_state="pending",
                        system_user_id=system_user_id,
                        created_at=stamp,
                        expires_at=expires_at,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                else:
                    return ReserveResult(won=True, existing=None)

            # A row already exists — inspect it.
            async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
                existing = await session.get(IdempotencyRecordTable, key)
                if existing is None:
                    continue  # vanished between commit-fail and read — retry insert
                if _expired(existing.expires_at, stamp):
                    await session.delete(existing)
                    await session.commit()
                    continue  # reclaimed — loop to re-insert
                return ReserveResult(won=False, existing=_to_row(existing))
        # Both attempts exhausted (pathological churn) — treat as conflict.
        return ReserveResult(won=False, existing=None)

    async def finalize_idempotency_record(
        self,
        *,
        key: str,
        response_status: int,
        response_body: dict[str, Any],
        bus_state: str,
    ) -> None:
        """Attach the produced response to a reserved record."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(IdempotencyRecordTable, key)
            if row is None:  # reservation was reclaimed under us — nothing to finalize
                return
            row.response_status = response_status
            row.response_body = response_body
            row.bus_state = bus_state
            session.add(row)
            await session.commit()

    async def purge_expired_idempotency(self, *, now: datetime | None = None) -> int:
        """Delete expired rows; returns count. Housekeeping, not on the hot path."""
        stamp = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(IdempotencyRecordTable).where(
                    col(IdempotencyRecordTable.expires_at) <= stamp
                )
            )
            rows = list(result)
            for r in rows:
                await session.delete(r)
            await session.commit()
            return len(rows)


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


__all__ = ["IdempotencyMixin"]
