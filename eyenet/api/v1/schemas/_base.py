"""Shared base for every v1 API schema.

`ApiSchema` locks the wire-shape contract once: strict field validation
(`extra="forbid"`), alias-by-name population for FastAPI ergonomics, and
consistent JSON serialisation. Every schema in this package subclasses it.

API_PLAN §9.1, §9.5.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    """Base for every v1 HTTP API request/response model.

    Distinct from `eyenet.contracts._base.DbRowBase` and `BusEnvelope` —
    those describe storage rows and bus messages, not API surface. API
    schemas are projections (§9.5), not the canonical representation of
    anything.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=False,
        ser_json_inf_nan="constants",
    )


__all__ = ["ApiSchema"]
