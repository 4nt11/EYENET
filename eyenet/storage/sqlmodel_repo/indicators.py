# SPDX-License-Identifier: AGPL-3.0-or-later
"""IndicatorsMixin — the indicator-extraction ruleset (and, later, artifact mentions).

Generic SQLModel ORM only (ANSI SQL); no dialect-specific SQL lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import col, select

from eyenet.contracts.indicator import IndicatorRuleRow
from eyenet.models.indicator_rule import IndicatorRuleTable

from ._helpers import safe_session

if TYPE_CHECKING:
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


__all__ = ["IndicatorsMixin"]
