"""`TelegramCollectorStub` — synthetic envelope producer.

M1 only — produces deterministic synthetic `RawMessageEnvelope`s on a timer
or from a JSONL fixture file. Real telethon integration lands at M2. Lets
us verify the entire fleet plumbing before introducing network/SDK risk.
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


class TelegramCollectorStub(CollectorSkeleton):
    """Emits synthetic raw-message envelopes."""

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
            source_kind=SourceKind.TELEGRAM,
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
            subject_for(SourceKind.TELEGRAM, self.instance_id),
            env,
        )
        self._record_emission()

    def _build_envelope(self, record: dict[str, Any]) -> RawMessageEnvelope:
        body = str(record.get("body", ""))
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        platform_groupid = str(record.get("platform_groupid", "0"))
        platform_msgid = str(record.get("platform_msgid", "0"))
        sent_ts = record.get("sent_at_source")
        if isinstance(sent_ts, str):
            sent_at = datetime.fromisoformat(sent_ts)
        else:
            sent_at = datetime.now(tz=UTC)
        return RawMessageEnvelope(
            source=SourceKind.TELEGRAM,
            instance_id=self.instance_id,
            evidence_ref=f"telegram:{platform_groupid}:{platform_msgid}",
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


__all__ = ["TelegramCollectorStub"]
