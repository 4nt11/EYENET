# SPDX-License-Identifier: AGPL-3.0-or-later
"""HealthMixin — cheap liveness probe backing the /v1/readyz storage check."""

from __future__ import annotations

from sqlmodel import select

from ._helpers import safe_session


class HealthMixin:
    async def ping(self) -> None:
        """Cheap liveness read; raises if the backend is unreachable.

        Generic ANSI ``SELECT 1`` — no dialect-specific SQL, so every
        SQLModel backend shares this one implementation (no override).
        """
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            await session.exec(select(1))


__all__ = ["HealthMixin"]
