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


__all__ = [
    "STEALER_DONE",
    "STEALER_FAILED",
    "STEALER_RUNNING",
    "StealerProcessingTable",
]
