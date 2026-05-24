"""`MatrixCollectorStub` — synthetic envelope producer for Matrix.

Mirror of `TelegramCollectorStub`. Emits deterministic synthetic
`RawMessageEnvelope`s with `source=SourceKind.MATRIX` and Matrix-shaped
`evidence_ref`s from a JSONL fixture. Used by M7 integration tests to
prove the abstract factory holds across two source kinds without
introducing real network risk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eyenet.collectors.base.skeleton import CollectorSkeleton
from eyenet.contracts._base import TraceContext
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.raw_message import RawMessageEnvelope, subject_for
from eyenet.storage import SQLiteStorage
from eyenet.telemetry.propagation import current_traceparent


class MatrixCollectorStub(CollectorSkeleton):
    """Emits synthetic Matrix raw-message envelopes."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: SQLiteStorage,
        pool: IdentityPool,
        identity_name: str,
        fixture_path: Path | None = None,
    ) -> None:
        super().__init__(
            bus=bus,
            storage=storage,
            pool=pool,
            identity_name=identity_name,
            source_kind=SourceKind.MATRIX,
        )
        self._fixture_path = fixture_path
        self._fixture_iter: list[dict[str, Any]] = []
        if fixture_path and fixture_path.exists():
            with fixture_path.open(encoding="utf-8") as fh:
                self._fixture_iter = [json.loads(line) for line in fh if line.strip()]

    async def tick(self) -> None:
        if not self._fixture_iter:
            return
        record = self._fixture_iter.pop(0)
        env = self._build_envelope(record)
        await self.publisher.publish(
            subject_for(SourceKind.MATRIX, self.instance_id),
            env,
        )
        self._record_emission()

    def _build_envelope(self, record: dict[str, Any]) -> RawMessageEnvelope:
        body = str(record.get("body", ""))
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        # Matrix nomenclature: room_id maps to platform_groupid,
        # event_id maps to platform_msgid. Default placeholders preserve
        # the Telegram stub's "no-fixture row still emits something" shape.
        platform_groupid = str(record.get("platform_groupid", "!room:example.org"))
        platform_msgid = str(record.get("platform_msgid", "$event"))
        sent_ts = record.get("sent_at_source")
        sent_at = (
            datetime.fromisoformat(sent_ts) if isinstance(sent_ts, str) else datetime.now(tz=UTC)
        )
        return RawMessageEnvelope(
            source=SourceKind.MATRIX,
            instance_id=self.instance_id,
            evidence_ref=f"matrix:{platform_groupid}:{platform_msgid}",
            actor_key=str(record.get("actor_key", "actor:" + "0" * 64)),
            platform_groupid=platform_groupid,
            platform_msgid=platform_msgid,
            sent_at_source=sent_at,
            collected_at=datetime.now(tz=UTC),
            length_chars=len(body),
            length_words=len(body.split()),
            body_sha256=body_sha256,
            is_forward=bool(record.get("is_forward", False)),
            has_attachment=bool(record.get("has_attachment", False)),
            trace_context=TraceContext(
                traceparent=current_traceparent() or _zero_traceparent(),
            ),
        )


def _zero_traceparent() -> str:
    return "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


__all__ = ["MatrixCollectorStub"]
