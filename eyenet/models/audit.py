"""AuditLogTable — see contracts/audit.py.

Hash-chain integrity is a write-time discipline (`compute_self_hash`); the
DB layer's role is to keep rows append-only and indexed for the chain walk.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Index
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


class AuditLogTable(SQLModel, table=True):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_at", "at"),
        Index("ix_audit_event_at", "event", "at"),
        Index("ix_audit_subject", "subject_kind", "subject_id"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    event: str
    service: str = Field(index=True)
    instance_id: str
    # Cross-store reference (system_user lives in messages.db). Indexed UUID,
    # no FK enforcement — PLAN §5.2 forbids cross-store joins.
    system_user_id: UUID | None = Field(default=None, index=True)
    subject_kind: str
    subject_id: UUID | None = None
    evidence_ref: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    at: datetime
    prev_hash: str
    self_hash: str = Field(unique=True)


__all__ = ["AuditLogTable"]
