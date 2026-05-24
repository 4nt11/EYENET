"""RFC 7807 problem+json error envelope.

Every 4xx/5xx response across the v1 surface serializes a `ProblemDetail`.
Validation failures additionally populate `errors[]` with per-field
`ValidationError` rows.

OpenAPI: `contracts/openapi/eyenet.v1.yaml#/components/schemas/ProblemDetail`
API_PLAN §7.
"""

from __future__ import annotations

from pydantic import Field

from ._base import ApiSchema


class ValidationError(ApiSchema):
    """Per-field failure detail used in `ProblemDetail.errors[]` on 422."""

    loc: list[str | int] = Field(description="JSON-path-like field locator.")
    msg: str = Field(max_length=512)
    type: str = Field(max_length=128)


class ProblemDetail(ApiSchema):
    """RFC 7807 problem+json envelope for every EYENET error response."""

    type: str = Field(description="Absolute URI identifying the error class.")
    title: str = Field(max_length=256)
    status: int = Field(ge=100, le=599)
    detail: str | None = Field(default=None, max_length=2048)
    instance: str | None = Field(default=None, max_length=2048)
    request_id: str = Field(max_length=64)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    errors: list[ValidationError] = Field(default_factory=list)


__all__ = ["ProblemDetail", "ValidationError"]
