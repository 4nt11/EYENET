# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bus envelope + subject for external-witness anchors (API_PLAN §5.9)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_AUDIT_ANCHOR: str = "eyenet.audit.anchor"


class AnchorEnvelope(BusEnvelope):
    """`eyenet.audit.anchor` — a signed `(audit_head, journal_head)` heartbeat."""

    deployment_id: UUID
    anchor_seq: int = Field(ge=0)
    anchored_at: datetime
    audit_head: str
    journal_head: str
    signature: str


__all__ = ["SUBJECT_AUDIT_ANCHOR", "AnchorEnvelope"]
