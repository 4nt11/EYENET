# SPDX-License-Identifier: AGPL-3.0-or-later
"""DTOs for the rule-coverage-gaps endpoint.

A tiny operator triage surface: "for each stealer family we classify, what
fraction of victims have NO fingerprint extraction?" Guides rule-authoring
work by surfacing the families where one new ``userinfo_*_shape`` rule
unlocks the most victims.
"""

from __future__ import annotations

from ._base import ApiSchema


class RuleCoverageGapRow(ApiSchema):
    stealer_family: str
    total_victims: int
    with_fingerprint: int
    missing_fingerprint: int
    missing_pct: float


class RuleCoverageGapsResponse(ApiSchema):
    items: list[RuleCoverageGapRow]
    total_victims: int                  # sum across all families
    total_missing: int                  # sum of missing_fingerprint
    coverage_pct: float                 # overall fingerprint coverage
