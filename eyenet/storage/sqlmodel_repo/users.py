# SPDX-License-Identifier: AGPL-3.0-or-later
"""UsersMixin — system user profile CRUD (M9.A2).

Profile-only. Credentials, scope grants, and clearance grants live on
their own mixins (`AuthMixin`, `ClearanceMixin`) per the M9.A1 split.
ANSI SQL only (CLAUDE.md §2.3 Rule 1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import select

from eyenet.contracts.enums import SystemUserRole
from eyenet.contracts.system_user import SystemUserRow
from eyenet.models.system_user import SystemUserTable

from ._helpers import safe_session


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _user_row(table: SystemUserTable) -> SystemUserRow:
    data = table.model_dump()
    for k in ("created_at", "last_login_at"):
        data[k] = _coerce_utc(data.get(k))
    return SystemUserRow.model_validate(data)


class UsersMixin:
    """CRUD surface for ``system_user`` rows."""

    async def put_system_user(
        self,
        *,
        user_id: UUID,
        username: str,
        display_name: str,
        role: SystemUserRole,
        created_at: datetime,
        email: str | None = None,
        is_active: bool = True,
        notes: str | None = None,
    ) -> SystemUserRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            existing = await session.get(SystemUserTable, user_id)
            if existing is None:
                row = SystemUserTable(
                    id=user_id,
                    username=username,
                    display_name=display_name,
                    role=role,
                    created_at=created_at,
                    email=email,
                    is_active=is_active,
                    notes=notes,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _user_row(row)
            existing.username = username
            existing.display_name = display_name
            existing.role = role
            existing.email = email
            existing.is_active = is_active
            existing.notes = notes
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return _user_row(existing)

    async def get_system_user_by_id(self, user_id: UUID) -> SystemUserRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SystemUserTable, user_id)
            return _user_row(row) if row is not None else None

    async def get_system_user_by_username(self, username: str) -> SystemUserRow | None:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(
                select(SystemUserTable).where(SystemUserTable.username == username),
            )
            row = result.one_or_none()
            return _user_row(row) if row is not None else None

    async def record_system_user_login(
        self,
        *,
        user_id: UUID,
        at: datetime,
    ) -> SystemUserRow:
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = await session.get(SystemUserTable, user_id)
            if row is None:
                raise ValueError(f"system user {user_id} not found")
            row.last_login_at = at
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _user_row(row)


__all__ = ["UsersMixin"]
