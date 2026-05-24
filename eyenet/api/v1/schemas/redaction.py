"""Redaction marker — replaces sensitive content fields when caller lacks clearance.

API_PLAN §4.7. List/timeline endpoints return redaction markers in place of the
`content` (or any other sensitive field) when the row's `sensitivity` tier
exceeds the caller's clearance scope. Metadata stays visible on the parent
envelope — analysts can SEE that the row exists and ESCALATE.

Wire-shape mirror of `RedactionMarker` in `contracts/openapi/eyenet.v1.yaml`.
The field-level retrofit (wrapping every content-bearing field in
`<original> | RedactionMarker`) lands incrementally with the sensitivity-aware
handler work in M9.3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import ApiSchema
from .enums import SensitivityTier


class RedactionMarker(ApiSchema):
    """Returned in place of a redacted content field. `redacted` is always `True`."""

    redacted: Literal[True] = True
    tier: SensitivityTier = Field(description="Row's tier at access time.")
    reason: str = Field(max_length=256, description="Human-readable why-redacted message.")
    request_clearance_at: str | None = Field(
        default=None,
        max_length=256,
        description="Pointer to how to request clearance (e.g. `/v1/auth/me`).",
    )
    grant_request_subject: str | None = Field(
        default=None,
        max_length=128,
        description="Suggested subject line / case identifier for the clearance request.",
    )


__all__ = ["RedactionMarker"]
