# SPDX-License-Identifier: AGPL-3.0-or-later
"""SettingsMixin — the runtime key/value operator-settings store (app_setting).

Generic, dialect-free (Rule 1): SELECT-then-add upsert. app_setting is a handful of
rows read at low frequency (services cache the value), so the generic path is fine; a
concrete backend may override with ON CONFLICT if contention ever shows up.
"""

from __future__ import annotations

from sqlmodel import select

from eyenet.models import AppSettingTable
from eyenet.models._base import now_utc

from ._helpers import safe_session


class SettingsMixin:
    async def get_setting(self, key: str) -> str | None:
        """The raw string value for ``key``, or None if unset."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(select(AppSettingTable).where(AppSettingTable.key == key))
            ).first()
            return row.value if row is not None else None

    async def set_setting(self, key: str, value: str, *, updated_by: str | None = None) -> None:
        """Upsert ``key`` -> ``value`` (SELECT-then-add; generic, no dialect SQL)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = (
                await session.exec(select(AppSettingTable).where(AppSettingTable.key == key))
            ).first()
            if row is None:
                row = AppSettingTable(
                    key=key, value=value, updated_at=now_utc(), updated_by=updated_by
                )
            else:
                row.value = value
                row.updated_at = now_utc()
                row.updated_by = updated_by
            session.add(row)
            await session.commit()
