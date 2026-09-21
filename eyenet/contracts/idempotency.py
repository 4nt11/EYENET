"""Idempotency-record DTOs (API_PLAN §6/§10.3, MODELS §2.28).

Storage-return shapes for the write replay guard. Live in ``contracts`` so the
storage ABC and the concrete mixins share them without the ABC depending on the
concrete layer. Never cross the bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class IdempotencyRecordRow:
    key: str
    request_hash: str
    response_status: int | None
    response_body: dict[str, Any] | None
    bus_state: str
    system_user_id: UUID | None
    created_at: datetime
    expires_at: datetime

    @property
    def is_finalized(self) -> bool:
        return self.response_status is not None


@dataclass(frozen=True, slots=True)
class ReserveResult:
    """Outcome of a reservation attempt. ``won`` → caller runs the handler and
    finalizes; otherwise ``existing`` is the row already present (finalized to
    replay, or still ``pending`` for a concurrent-in-flight 409). ``existing``
    is None only on pathological reservation churn."""

    won: bool
    existing: IdempotencyRecordRow | None


__all__ = ["IdempotencyRecordRow", "ReserveResult"]
