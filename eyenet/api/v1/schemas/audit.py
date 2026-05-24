"""Audit-resource schemas — row projection + hash-chain verification result.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — AuditRow, AuditVerifyResult.
API_PLAN §3.3, §5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from eyenet.models.audit import AuditLogTable

from ._base import ApiSchema
from .pagination import CursorPage


class AuditRow(ApiSchema):
    """Projection of MODELS.md §2.16 AuditLog for `GET /v1/audit`.

    Field renames: domain `at` -> `ts`, domain `event` -> `subject`,
    domain `self_hash` -> `hash`, domain `system_user_id` -> `user_id`.

    TODO(M9.1): the domain row does not currently store `request_id`; the
    audit-emission middleware lands the field as part of M9.0 wire-up.
    Until then `from_domain` leaves it `None`.
    """

    event_id: UUID
    subject: str = Field(max_length=128)
    user_id: UUID | None = None
    ts: datetime
    request_id: str | None = Field(default=None, max_length=64)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str = Field(max_length=128)
    hash: str = Field(max_length=128)

    @classmethod
    def from_domain(cls, row: AuditLogTable) -> AuditRow:
        # request_id sits in payload until the audit table grows a column.
        request_id = row.payload.get("request_id") if isinstance(row.payload, dict) else None
        return cls(
            event_id=row.id,
            subject=row.event,
            user_id=row.system_user_id,
            ts=row.at,
            request_id=request_id if isinstance(request_id, str) else None,
            trace_id=row.trace_id,
            span_id=row.span_id,
            payload=row.payload or {},
            prev_hash=row.prev_hash,
            hash=row.self_hash,
        )


class AuditChainBreak(ApiSchema):
    """First detected divergence between recomputed and stored hash chains."""

    event_id: UUID
    expected_hash: str
    actual_hash: str


class AuditVerifyResult(ApiSchema):
    """200 response for `GET /v1/audit/verify`."""

    verified: bool
    rows_checked: int = Field(ge=0)
    first_break: AuditChainBreak | None = None


class CursorPageAuditRow(CursorPage[AuditRow]):
    """200 page response for `GET /v1/audit`."""


__all__ = [
    "AuditChainBreak",
    "AuditRow",
    "AuditVerifyResult",
    "CursorPageAuditRow",
]
