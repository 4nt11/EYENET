# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stealer-log ULP processing state — one row per attachment the processor handled.

Tracks the outcome of decrypt → extract → ulpextract → ClickHouse ingest for a
stealer-marked attachment, so the StealerProcessorService never reprocesses a done
blob and the operator can see what happened (creds extracted, errors, attempts).
State is a plain varchar (``running``/``done``/``failed``) — open, no DB enum.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

# Processing lifecycle states (plain strings; no DB enum).
STEALER_RUNNING = "running"
STEALER_DONE = "done"
STEALER_FAILED = "failed"


class StealerProcessingTable(SQLModel, table=True):
    __tablename__ = "stealer_processing"

    attachment_id: UUID = Field(foreign_key="attachment.id", primary_key=True)
    state: str = Field(default=STEALER_RUNNING, index=True)
    creds_extracted: int = 0
    error: str | None = None
    attempts: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class StealerFamilyOverrideTable(SQLModel, table=True):
    """Operator verdict override for per-victim family classification.

    An override is a human-sourced ground-truth label on one (archive,
    victim) pair. Overrides are the labeled set that tunes the scorer's
    weights (see development/STEALER_FAMILY_CLASSIFIER_DESIGN.md
    Phase 7). The classifier-produced verdict stays in ClickHouse
    (victim_family_verdict); overrides live here in Postgres because
    they are operator actions tracked alongside other audit-relevant
    writes (clearance, PAT mint/revoke, case ops).
    """

    __tablename__ = "stealer_family_override"

    archive_sha256: str = Field(primary_key=True, max_length=64)
    victim_folder: str = Field(primary_key=True, max_length=512)
    slug: str = Field(index=True, max_length=64)
    reason: str | None = Field(default=None, max_length=512)
    author_user_id: UUID = Field(foreign_key="system_user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


__all__ = [
    "STEALER_DONE",
    "STEALER_FAILED",
    "STEALER_RUNNING",
    "StealerFamilyOverrideTable",
    "StealerProcessingTable",
]
