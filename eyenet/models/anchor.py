# SPDX-License-Identifier: AGPL-3.0-or-later
"""AuditAnchorTable — see contracts/anchor.py (API_PLAN §5.9).

Lives in `main.db`: a derived external-witness log, not part of either
tamper-evident chain (it merely records their heads). ANSI-only constraints.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class AuditAnchorTable(SQLModel, table=True):
    """Persisted external-witness anchor record (API_PLAN §5.9)."""

    __tablename__ = "audit_anchor"
    __table_args__ = (
        # One row per (deployment, seq); the emitter allocates seq = latest + 1.
        Index("ux_anchor_deployment_seq", "deployment_id", "anchor_seq", unique=True),
        # Read path: newest-first per window.
        Index("ix_anchor_anchored_at", "anchored_at"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    deployment_id: UUID = Field(index=True)
    anchor_seq: int
    anchored_at: datetime
    audit_head: str = Field(max_length=64)
    journal_head: str = Field(max_length=64)
    signature: str = Field(max_length=256)


__all__ = ["AuditAnchorTable"]
