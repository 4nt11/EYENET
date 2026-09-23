# SPDX-License-Identifier: AGPL-3.0-or-later
"""AnchorEmitter — periodic external-witness anchor heartbeat (API_PLAN §5.9).

Every tick, records a signed ``(audit_head, journal_head)`` snapshot and
publishes it on ``eyenet.audit.anchor``. Purely tick-driven; no subscriptions.
Operator-configured external sinks (file/webhook/email) consume the bus subject
and are a separate deliverer — not built here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from eyenet.contracts._base import TraceContext
from eyenet.contracts.anchor_events import SUBJECT_AUDIT_ANCHOR, AnchorEnvelope
from eyenet.crypto import (
    build_anchor_canonical,
    load_anchor_key,
    load_or_create_deployment_id,
)
from eyenet.service import ServiceBase
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

if TYPE_CHECKING:
    from pathlib import Path

    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository


class AnchorEmitter(ServiceBase):
    """Signs and records an anchor each tick (§5.9)."""

    def __init__(self, *, bus: Bus, storage: BaseRepository, data_dir: Path) -> None:
        super().__init__(bus=bus, storage=storage)
        self._signer = load_anchor_key(data_dir)
        self._deployment_id = load_or_create_deployment_id(data_dir)

    @property
    def name(self) -> str:
        return "anchor_emitter"

    @property
    def instance_id(self) -> str:
        return "anchor_default"

    async def on_subscribe(self) -> None:
        """No bus subscription — purely tick-driven."""

    async def tick(self) -> None:
        await self.emit_anchor()

    async def emit_anchor(self) -> None:
        audit_head = await self.storage.audit_head()
        journal_head = (await self.storage.file_access_journal_head()).hex()
        anchor_seq = (await self.storage.latest_anchor_seq(self._deployment_id)) + 1
        anchored_at = datetime.now(tz=UTC)

        signature = self._signer.sign(
            build_anchor_canonical(
                deployment_id=self._deployment_id,
                anchor_seq=anchor_seq,
                anchored_at=anchored_at.isoformat(),
                audit_head=audit_head,
                journal_head=journal_head,
            )
        )
        await self.storage.record_anchor(
            deployment_id=self._deployment_id,
            anchor_seq=anchor_seq,
            anchored_at=anchored_at,
            audit_head=audit_head,
            journal_head=journal_head,
            signature=signature,
        )
        await self.publisher.publish(
            SUBJECT_AUDIT_ANCHOR,
            AnchorEnvelope(
                trace_context=TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT),
                deployment_id=self._deployment_id,
                anchor_seq=anchor_seq,
                anchored_at=anchored_at,
                audit_head=audit_head,
                journal_head=journal_head,
                signature=signature,
            ),
        )


__all__ = ["AnchorEmitter"]
