# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stealer-log capture event — drives the ULP processing pipeline.

Emitted by a collector when it stores an attachment blob on a stealer-marked channel
(category=stealer_logs with a storage_uri). The StealerProcessorService subscribes
(queue_group for horizontal fan-out) and runs decrypt → extract → ulpextract →
ClickHouse ingest for the one attachment named here. Carries a POINTER (attachment id),
never payload — the service reads the blob + message body from storage.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope

SUBJECT_STEALER_ATTACHMENT_CAPTURED: str = "stealer.attachment.captured"


class StealerAttachmentCapturedEnvelope(BusEnvelope):
    """A stealer-log archive blob was captured; process it into creds."""

    attachment_id: UUID = Field(description="PK of the stored stealer attachment")


__all__ = [
    "SUBJECT_STEALER_ATTACHMENT_CAPTURED",
    "StealerAttachmentCapturedEnvelope",
]
