# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request/response schemas for the indicator-rule CRUD surface.

Create validates at the write boundary: ``kind`` must be a known
InfrastructureKind, and ``pattern`` must compile under RE2 (which rejects
lookbehind/backreferences), so an invalid rule is a 422 here, never a silent
skip at extraction time.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import re2
from pydantic import Field, field_validator

from eyenet.contracts.enums import InfrastructureKind
from eyenet.contracts.indicator import IndicatorRuleRow

from ._base import ApiSchema

_VALID_KINDS = frozenset(k.value for k in InfrastructureKind)


class IndicatorRuleOut(ApiSchema):
    id: UUID
    kind: str
    pattern: str
    fold_case: bool
    enabled: bool
    vendored: bool
    description: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: IndicatorRuleRow) -> IndicatorRuleOut:
        return cls(**row.model_dump())


class IndicatorRuleCreate(ApiSchema):
    kind: str = Field(description="InfrastructureKind value the match is stored under")
    pattern: str = Field(min_length=1, max_length=512)
    fold_case: bool = True
    description: str = ""
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _kind_known(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"unknown kind {v!r}; must be one of {sorted(_VALID_KINDS)}")
        return v

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, v: str) -> str:
        try:
            re2.compile(v)
        except re2.error as exc:
            raise ValueError(f"invalid RE2 pattern (no lookbehind/backreferences): {exc}") from exc
        return v


class IndicatorRuleUpdate(ApiSchema):
    enabled: bool | None = None
    description: str | None = None


__all__ = [
    "IndicatorRuleCreate",
    "IndicatorRuleOut",
    "IndicatorRuleUpdate",
]
