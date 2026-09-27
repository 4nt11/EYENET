"""IncidentRuleTable — operator-defined incident detection rules.

An operator rule is an RE2 pattern that maps a match to a taxonomy label, layered ON TOP
of the built-in field-grounded prefilter signals (eyenet/incidents/prefilter.py) — it does
not modify them. The classifier service loads enabled rules and fires them alongside the
built-ins, so an operator can add/adjust detection live without a redeploy.

`name` is unique and must not collide with a built-in signal name (validated at create).
`label` must be a taxonomy head. `pattern` is validated as compilable RE2 at create time.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class IncidentRuleTable(SQLModel, table=True):
    __tablename__ = "incident_rule"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    name: str = Field(index=True, unique=True)
    pattern: str
    label: str
    weight: int = 2
    enabled: bool = Field(default=True, index=True)
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
