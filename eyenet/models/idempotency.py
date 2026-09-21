# SPDX-License-Identifier: AGPL-3.0-or-later
"""IdempotencyRecordTable — see MODELS.md §2.28.

Cross-worker replay guard for every ``/v1/`` write carrying an
``Idempotency-Key`` (API_PLAN §6 invariant #6, §10.3). Lives in ``main``.
A replay of a seen key returns the stored ``response_status`` + ``response_body``
verbatim without re-emitting bus events; a live key reused with a different
``request_hash`` is a 409.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class IdempotencyRecordTable(SQLModel, table=True):
    __tablename__ = "idempotency_record"

    key: str = Field(primary_key=True, max_length=128)
    request_hash: str
    # response_status/body are nullable while the record is a `pending`
    # reservation; finalized once the handler produces its response.
    response_status: int | None = None
    response_body: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    bus_state: str = Field(default="pending")  # pending | delivered
    system_user_id: UUID | None = Field(default=None, index=True)
    created_at: datetime
    expires_at: datetime = Field(index=True)


__all__ = ["IdempotencyRecordTable"]
