# SPDX-License-Identifier: AGPL-3.0-or-later
"""`StealerProcessing` contract — ULP pipeline per-attachment state (MODELS: stealer).

Surface: db.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ._base import DbRowBase


class StealerProcessingRow(DbRowBase):
    """Processing outcome for one stealer-marked attachment.

    ``state`` ∈ {running, done, failed}. ``creds_extracted`` is the row count the last
    successful ingest produced; ``error`` the last failure message; ``attempts`` the
    retry count."""

    attachment_id: UUID
    state: str
    creds_extracted: int = 0
    error: str | None = None
    attempts: int = 0
    updated_at: datetime


class StealerFamilyOverrideRow(DbRowBase):
    """Operator verdict ground-truth for one (archive, victim) pair.

    An override is a human attribution of a stealer family to a specific
    victim. Overrides win over the classifier verdict at drawer read time
    and feed the tuning P/R dashboard."""

    archive_sha256: str
    victim_folder: str
    slug: str
    reason: str | None = None
    author_user_id: UUID
    created_at: datetime
    updated_at: datetime


__all__ = ["StealerFamilyOverrideRow", "StealerProcessingRow"]
