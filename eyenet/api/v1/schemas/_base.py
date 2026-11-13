"""Shared base for every v1 API schema.

`ApiSchema` locks the wire-shape contract once: strict field validation
(`extra="forbid"`), alias-by-name population for FastAPI ergonomics, and
consistent JSON serialisation. Every schema in this package subclasses it.

API_PLAN §9.1, §9.5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer


class ApiSchema(BaseModel):
    """Base for every v1 HTTP API request/response model.

    Distinct from `eyenet.contracts._base.DbRowBase` and `BusEnvelope` (those
    describe storage rows and bus messages, not API surface). API schemas are
    projections (§9.5), not the canonical representation of anything.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=False,
        ser_json_inf_nan="constants",
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_naive_datetime_as_utc(self, value: Any) -> Any:
        # SQLite stores datetimes without timezone. When read back they are
        # naive and Pydantic emits them without a TZ suffix. OpenAPI declares
        # format: date-time (RFC 3339) for every datetime field, which
        # requires an offset. Re-stamp naive datetimes as UTC so the serialized
        # form matches the schema. Aware values are emitted as-is.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


__all__ = ["ApiSchema"]
