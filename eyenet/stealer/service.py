# SPDX-License-Identifier: AGPL-3.0-or-later
"""StealerProcessorService — event-driven ULP processing, running alongside the stack.

Subscribes (queue_group ``stealer`` = horizontal fan-out, plural from day one) to
``stealer.attachment.captured`` and, at boot, replays stealer-marked blobs that were
captured while it was down or marked after capture. For each attachment: recover the
archive password from the promo message body, then decrypt → extract → ulpextract →
ClickHouse (the heavy, subprocess-bound work runs via ``asyncio.to_thread`` so it never
blocks the event loop). Records terminal state so nothing reprocesses; a mid-run crash
leaves no ``done`` row, so the next boot's replay retries it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.contracts.group import STEALER_LOG_CATEGORY
from eyenet.contracts.stealer_events import (
    SUBJECT_STEALER_ATTACHMENT_CAPTURED,
    StealerAttachmentCapturedEnvelope,
)
from eyenet.models.stealer import STEALER_DONE, STEALER_FAILED
from eyenet.service import ServiceBase
from eyenet.stealer.clickhouse import ClickHouseCredsSink
from eyenet.stealer.password import parse_password, password_candidates
from eyenet.stealer.pipeline import process_archive
from eyenet.telemetry.logging import get_logger
from eyenet.telemetry.propagation import attach_from_headers

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

_log = get_logger()
# How many unprocessed blobs the boot replay drains (these are heavy multi-GB jobs).
_REPLAY_LIMIT = 1000


class StealerProcessorService(ServiceBase):
    """Turns captured stealer archives into queryable creds, off the bus."""

    def __init__(
        self, *, bus: Bus, storage: BaseRepository, instance_id: str = "stealer_processor_1"
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._instance_id = instance_id
        self._sink = ClickHouseCredsSink()
        # Scratch space for the (large) archive extraction; cleaned per-archive.
        self._work_root = Path(
            os.environ.get("EYENET_STEALER_WORK_DIR", "/var/lib/eyenet/stealer-work")
        )
        self._replay_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "stealer_processor"

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def on_subscribe(self) -> None:
        async def _on_captured(_s: str, p: bytes, h: dict[str, str]) -> None:
            asyncio.create_task(self._process(p, h))  # noqa: RUF006 — fire-and-track below

        await self._bus.subscribe(
            SUBJECT_STEALER_ATTACHMENT_CAPTURED, _on_captured, queue_group="stealer"
        )
        # Boot replay: archives captured while down, or channels marked after capture.
        self._replay_task = asyncio.create_task(self._replay_unprocessed())

    async def _process(self, payload: bytes, headers: dict[str, str]) -> None:
        # Tracing attach INSIDE the task body (the create_task runs later, §4.5).
        with attach_from_headers(headers):
            try:
                env = StealerAttachmentCapturedEnvelope.model_validate_json(payload)
                await self._process_attachment(env.attachment_id)
            except Exception as exc:
                _log.error("stealer_processor.handler_error", error=str(exc))

    async def _replay_unprocessed(self) -> None:
        try:
            rows = await self._storage.list_unprocessed_stealer_attachments(
                STEALER_LOG_CATEGORY, limit=_REPLAY_LIMIT
            )
        except Exception as exc:
            _log.error("stealer_processor.replay_list_failed", error=str(exc))
            return
        _log.info("stealer_processor.replay", pending=len(rows))
        for att in rows:  # serial — multi-GB extractions; don't stampede disk/CPU
            try:
                await self._process_attachment(att.id)
            except Exception as exc:
                _log.error("stealer_processor.replay_item_failed", attachment=str(att.id),
                           error=str(exc))

    async def _process_attachment(self, attachment_id: UUID) -> None:
        existing = await self._storage.get_stealer_processing(attachment_id)
        if existing is not None and existing.state == STEALER_DONE:
            return  # idempotent — already ingested
        att = await self._storage.get_attachment(attachment_id)
        if att is None or not att.storage_uri:
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_FAILED, error="attachment missing or no blob"
            )
            return
        # Password from the promo message body (self-watermark handle / literal).
        msg = await self._storage.get_message(att.message_id)
        body = getattr(msg, "body", "") or ""
        candidates = password_candidates(parse_password(body))
        result = await asyncio.to_thread(
            process_archive,
            blob_path=Path(att.storage_uri),
            password_candidates=candidates,
            work_root=self._work_root,
            sink=self._sink,
            source_label=f"attachment:{attachment_id}",
        )
        if result.ok:
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_DONE, creds_extracted=result.creds_inserted
            )
            _log.info("stealer_processor.done", attachment=str(attachment_id),
                      creds=result.creds_inserted, password_used=bool(result.password_used))
        else:
            await self._storage.set_stealer_processing(
                attachment_id, state=STEALER_FAILED, error=result.error
            )
            _log.warning("stealer_processor.failed", attachment=str(attachment_id),
                         error=result.error)

    async def shutdown(self) -> None:
        self._sink.close()
        await super().shutdown()


__all__ = ["StealerProcessorService"]
