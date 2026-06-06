# SPDX-License-Identifier: AGPL-3.0-or-later
"""IdentityMixin — DB-backed operator-identity CRUD + discovery-loop role state.

ANSI SQL only (CLAUDE.md §2.3 Rule 1). The DB ``IdentityTable`` is the source
of truth for the discovery-loop role/state/graduation machine (API_PLAN §4.12);
the file-backed pool (:class:`eyenet.identity_pool.file.FileIdentityPool`) stays
the credential/session store. The file↔DB provisioning bridge lands with E5 —
until then identities are seeded into the DB directly (tests, future provision
CLI) and an empty table correctly yields ``has_available_scout() == False``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, null
from sqlmodel import col, select

from eyenet.contracts.enums import IdentityRole, IdentityState
from eyenet.contracts.identity import IdentityRow
from eyenet.models.collector import CollectorTable
from eyenet.models.identity import IdentityTable
from eyenet.models.membership import CollectorGroupMembershipTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _identity_row(table: IdentityTable) -> IdentityRow:
    data = table.model_dump()
    for k in ("last_used_at", "graduated_at"):
        data[k] = _coerce_utc(data.get(k))
    return IdentityRow.model_validate(data)


class IdentitiesMixin:
    """CRUD + role/state-write surface for IdentityTable (API_PLAN §4.12)."""

    async def create_identity(
        self,
        *,
        name: str,
        source_id: UUID,
        session_path: str,
        role: IdentityRole = IdentityRole.MONITOR,
        state: IdentityState = IdentityState.AVAILABLE,
        proxy_uri: str | None = None,
        cooldown_seconds: int = 21_600,
        notes: str | None = None,
    ) -> IdentityRow:
        """Insert a new identity row. Raises on duplicate ``name`` (UNIQUE)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = IdentityTable(
                name=name,
                source_id=source_id,
                session_path=session_path,
                role=role,
                state=state,
                proxy_uri=proxy_uri,
                cooldown_seconds=cooldown_seconds,
                notes=notes,
            )
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def get_identity(self, identity_id: UUID) -> IdentityRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IdentityTable, identity_id)
            return _identity_row(table) if table is not None else None

    async def list_identities(
        self,
        *,
        source_id: UUID | None = None,
        role: IdentityRole | None = None,
        state: IdentityState | None = None,
    ) -> list[IdentityRow]:
        """Return identities matching the (AND-combined) filters, name-ordered."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(IdentityTable)
            if source_id is not None:
                stmt = stmt.where(IdentityTable.source_id == source_id)
            if role is not None:
                stmt = stmt.where(IdentityTable.role == role)
            if state is not None:
                stmt = stmt.where(IdentityTable.state == state)
            stmt = stmt.order_by(col(IdentityTable.name).asc())
            result = await session.exec(stmt)
            return [_identity_row(r) for r in list(result)]

    async def set_identity_role(
        self,
        *,
        identity_id: UUID,
        role: IdentityRole,
    ) -> IdentityRow:
        """Set an identity's discovery-loop role. Raises if it does not exist."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IdentityTable, identity_id)
            if table is None:
                raise ValueError(f"identity {identity_id} not found")
            table.role = role
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def set_identity_state(
        self,
        *,
        identity_id: UUID,
        state: IdentityState,
    ) -> IdentityRow:
        """Set an identity's lifecycle state. Raises if it does not exist."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IdentityTable, identity_id)
            if table is None:
                raise ValueError(f"identity {identity_id} not found")
            table.state = state
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def graduate_identity(
        self,
        *,
        identity_id: UUID,
        now: datetime | None = None,
    ) -> IdentityRow:
        """Promote a SCOUT to MONITOR after a clean window (M9.E4 §4.12.5).

        Sets ``role=MONITOR`` and ``graduated_at``. Raises if the identity
        does not exist.
        """
        at = now or datetime.now(tz=UTC)
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IdentityTable, identity_id)
            if table is None:
                raise ValueError(f"identity {identity_id} not found")
            table.role = IdentityRole.MONITOR
            table.graduated_at = at
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def burn_identity(
        self,
        *,
        identity_id: UUID,
    ) -> IdentityRow:
        """Quarantine a burned identity (M9.E4 §4.12.5).

        Sets ``state=BURNED`` and ``role=QUARANTINE`` — the identity never
        re-enters rotation. Raises if it does not exist.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IdentityTable, identity_id)
            if table is None:
                raise ValueError(f"identity {identity_id} not found")
            table.state = IdentityState.BURNED
            table.role = IdentityRole.QUARANTINE
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def find_available_scout(self, source_id: UUID) -> IdentityRow | None:
        """Return an AVAILABLE SCOUT for ``source_id`` (API_PLAN §4.12.3), or None.

        Name-ordered so selection is deterministic. The supervisor leases the
        returned identity via the pool before dispatching a join.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IdentityTable)
                .where(
                    IdentityTable.source_id == source_id,
                    IdentityTable.role == IdentityRole.SCOUT,
                    IdentityTable.state == IdentityState.AVAILABLE,
                )
                .order_by(col(IdentityTable.name).asc())
                .limit(1)
            )
            result = await session.exec(stmt)
            table = result.first()
            return _identity_row(table) if table is not None else None

    async def lease_scout(self, source_id: UUID) -> IdentityRow | None:
        """Atomically claim an AVAILABLE SCOUT for ``source_id`` (M9.E3).

        Selects the name-ordered first available scout and flips it to
        ``IN_USE`` in one transaction, so a subsequent lease can't re-grab it
        (the single-supervisor sequential case). Returns ``None`` when none are
        available. Cross-process concurrency would need a ``BEGIN IMMEDIATE``
        override in the SQLite backend, like the audit chain (CLAUDE.md §2.6);
        deferred while there is one supervisor process.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IdentityTable)
                .where(
                    IdentityTable.source_id == source_id,
                    IdentityTable.role == IdentityRole.SCOUT,
                    IdentityTable.state == IdentityState.AVAILABLE,
                )
                .order_by(col(IdentityTable.name).asc())
                .limit(1)
            )
            table = (await session.exec(stmt)).first()
            if table is None:
                return None
            table.state = IdentityState.IN_USE
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _identity_row(table)

    async def list_graduating_scouts(self, joined_before: datetime) -> list[UUID]:
        """Identity ids of SCOUTs whose collector has held an active membership
        since at or before ``joined_before`` (M9.E4 §4.12.5).

        A still-active membership (``left_at IS NULL``) that old is, by
        definition, a clean observation window — a ban would have closed it.
        Joins identity → collector (one identity per collector) → membership.
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(IdentityTable.id)
                .join(CollectorTable, col(CollectorTable.identity_id) == col(IdentityTable.id))
                .join(
                    CollectorGroupMembershipTable,
                    col(CollectorGroupMembershipTable.collector_id) == col(CollectorTable.id),
                )
                .where(
                    IdentityTable.role == IdentityRole.SCOUT,
                    col(CollectorGroupMembershipTable.left_at) == null(),
                    CollectorGroupMembershipTable.joined_at <= joined_before,
                )
                .distinct()
            )
            result = await session.exec(stmt)
            return list(result)

    async def has_available_scout(self, source_id: UUID) -> bool:
        """True iff at least one AVAILABLE SCOUT exists for ``source_id``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(func.count())
                .select_from(IdentityTable)
                .where(
                    IdentityTable.source_id == source_id,
                    IdentityTable.role == IdentityRole.SCOUT,
                    IdentityTable.state == IdentityState.AVAILABLE,
                )
            )
            result = await session.exec(stmt)
            return int(result.one()) > 0


__all__ = ["IdentitiesMixin"]
