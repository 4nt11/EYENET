# SPDX-License-Identifier: AGPL-3.0-or-later
"""IndicatorRuleTable — the operator-tunable extraction ruleset (Wazuh-style).

The `IndicatorExtractor` (a `DiscoveryExtractor`) compiles its regexes from the
ENABLED rows of this table, instead of hard-coding them. Vendored defaults ship
seeded by the Postgres migration (``vendored=True``); the operator disables one
(``enabled=False``) or adds a custom row (``vendored=False``) through the API,
exactly like Wazuh's vendored-rules-plus-local-overrides split.

Upgrade invariant: a future migration seeds new vendored rows with
``INSERT ... ON CONFLICT DO NOTHING`` and NEVER rewrites ``enabled`` — an
operator disable survives upgrades.

``kind`` is the :class:`InfrastructureKind` value a match is stored under (the
``infrastructure_artifact.kind`` column is that typed enum, so for v1 custom rules
are constrained to existing kinds). It is stored as a plain string here so the
ruleset table carries no enum-migration coupling.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ._base import new_uuid7, now_utc


class IndicatorRuleTable(SQLModel, table=True):
    """`indicator_rule` — one extraction pattern. Vendored default or operator-custom."""

    __tablename__ = "indicator_rule"
    __table_args__ = (UniqueConstraint("kind", "pattern", name="uq_indicator_rule_kind_pattern"),)

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # InfrastructureKind value the match is stored under (e.g. "wallet_btc").
    kind: str = Field(index=True)
    pattern: str
    # Normalize matched values with lower() before dedup. OFF for base58 kinds
    # (TRON/Monero/BTC-legacy) where case is significant.
    fold_case: bool = True
    # Operator state. Vendored upgrades MUST NOT touch this column.
    enabled: bool = Field(default=True, index=True)
    # True = shipped default; False = operator custom.
    vendored: bool = False
    description: str = ""
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


__all__ = ["IndicatorRuleTable"]
