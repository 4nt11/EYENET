# SPDX-License-Identifier: AGPL-3.0-or-later
"""IndicatorsMixin — the indicator-extraction ruleset (and, later, artifact mentions).

Generic SQLModel ORM only (ANSI SQL); no dialect-specific SQL lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import col, select

from eyenet.contracts.indicator import IndicatorRuleRow
from eyenet.models._base import now_utc
from eyenet.models.indicator_rule import IndicatorRuleTable

from ._helpers import safe_session

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: F401


def _coerce_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _rule_row(table: IndicatorRuleTable) -> IndicatorRuleRow:
    data = table.model_dump()
    for k in ("created_at", "updated_at"):
        data[k] = _coerce_utc(data[k])
    return IndicatorRuleRow.model_validate(data)


class IndicatorsMixin:
    """Indicator ruleset CRUD (read in Phase 2; writes land with the API)."""

    async def list_indicator_rules(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[IndicatorRuleRow]:
        """Return indicator rules, newest first. ``enabled_only`` filters to the
        rules the extractor actually runs."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(IndicatorRuleTable)
            if enabled_only:
                stmt = stmt.where(col(IndicatorRuleTable.enabled).is_(True))
            stmt = stmt.order_by(col(IndicatorRuleTable.created_at).desc())
            result = await session.exec(stmt)
            return [_rule_row(r) for r in list(result)]

    async def get_indicator_rule(self, rule_id: UUID) -> IndicatorRuleRow | None:
        """Return one rule by id, or ``None``."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IndicatorRuleTable, rule_id)
            return _rule_row(table) if table is not None else None

    async def create_indicator_rule(
        self,
        *,
        kind: str,
        pattern: str,
        fold_case: bool = True,
        description: str = "",
        enabled: bool = True,
    ) -> IndicatorRuleRow:
        """Create an operator-custom rule (``vendored=False``). A duplicate
        ``(kind, pattern)`` raises IntegrityError -> 409 via the app handler."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            row = IndicatorRuleTable(
                kind=kind,
                pattern=pattern,
                fold_case=fold_case,
                enabled=enabled,
                vendored=False,
                description=description,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _rule_row(row)

    async def update_indicator_rule(
        self,
        *,
        rule_id: UUID,
        enabled: bool | None = None,
        description: str | None = None,
    ) -> IndicatorRuleRow | None:
        """Patch ``enabled`` / ``description`` (``None`` = leave unchanged). Returns
        the updated row, or ``None`` if the rule does not exist. Pattern and kind
        are immutable here — change a custom rule by delete + recreate."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IndicatorRuleTable, rule_id)
            if table is None:
                return None
            if enabled is not None:
                table.enabled = enabled
            if description is not None:
                table.description = description
            table.updated_at = now_utc()
            session.add(table)
            await session.commit()
            await session.refresh(table)
            return _rule_row(table)

    async def delete_indicator_rule(self, rule_id: UUID) -> bool:
        """Delete a rule. Returns ``True`` if a row was removed. The caller
        guards vendored rules (they disable, never delete)."""
        async with safe_session(self._session_factory) as session:  # type: ignore[attr-defined]
            table = await session.get(IndicatorRuleTable, rule_id)
            if table is None:
                return False
            await session.delete(table)
            await session.commit()
            return True


__all__ = ["IndicatorsMixin"]
