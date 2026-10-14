# SPDX-License-Identifier: AGPL-3.0-or-later
"""Indicator-extraction ruleset row (the tunable, Wazuh-style rule). Surface: db."""

from __future__ import annotations

from datetime import datetime

from ._base import DbRowBase


class IndicatorRuleRow(DbRowBase):
    """One extraction rule: a regex + the InfrastructureKind its matches store under."""

    kind: str
    pattern: str
    fold_case: bool
    enabled: bool
    vendored: bool
    description: str
    created_at: datetime
    updated_at: datetime


__all__ = ["IndicatorRuleRow"]
