# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-driven reindex endpoints (admin:stealer).

- POST /v1/stealer/attachments/{attachment_id}/reindex: replay the full
  extract + classify pipeline against one stored attachment. Async via
  the bus (SUBJECT_STEALER_ATTACHMENT_REINDEX). Verifies the attachment
  exists before publishing so a bad UUID does not sit on the bus.

- POST /v1/stealer/reindex: full-corpus reindex sweep via the bus
  (SUBJECT_STEALER_CORPUS_REINDEX). Processor walks every stealer-
  category attachment and replays each through the pipeline, serial
  (multi-GB extractions).

Both admin:stealer and audited. The processor is the single source of
truth for "process this blob"; the API just pokes it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher, get_storage
from eyenet.api.v1.schemas.stealer import StealerReindexResponse
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.stealer_events import (
    SUBJECT_STEALER_ATTACHMENT_REINDEX,
    SUBJECT_STEALER_CORPUS_REINDEX,
    StealerAttachmentReindexEnvelope,
    StealerCorpusReindexEnvelope,
)
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent


def _tc() -> TraceContext:
    """Build a TraceContext for a bus envelope published from an HTTP
    handler. Uses the current span's traceparent when one is active;
    falls back to the zero value when tracing is not wired."""
    return TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT)


router = APIRouter(tags=["stealer"])


@router.post(
    "/stealer/attachments/{attachment_id}/reindex",
    operation_id="stealer_attachment_reindex",
    response_model=StealerReindexResponse,
    status_code=202,
)
async def stealer_attachment_reindex(
    attachment_id: Annotated[UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerReindexResponse:
    """Reindex ONE attachment. Fails fast with 404 if the attachment is
    unknown or has no stored blob; publishes the reindex event only
    when the preconditions hold."""
    att = await storage.get_attachment(attachment_id)
    if att is None:
        raise HTTPException(404, "attachment not found")
    if not att.storage_uri:
        raise HTTPException(409, "attachment has no stored blob")
    env = StealerAttachmentReindexEnvelope(
        attachment_id=attachment_id,
        requested_by=current_user.user_id,
        trace_context=_tc(),
    )
    await publisher.publish(SUBJECT_STEALER_ATTACHMENT_REINDEX, env)
    await audit.emit(
        event="eyenet.audit.stealer_attachment.reindex_requested",
        subject_kind="stealer_attachment",
        subject_id=attachment_id,
        system_user_id=current_user.user_id,
        payload={"storage_uri": att.storage_uri},
    )
    return StealerReindexResponse(queued=True, attachment_id=str(attachment_id))


@router.post(
    "/stealer/reindex",
    operation_id="stealer_corpus_reindex",
    response_model=StealerReindexResponse,
    status_code=202,
)
async def stealer_corpus_reindex(
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerReindexResponse:
    """Full-corpus reindex sweep via the bus."""
    env = StealerCorpusReindexEnvelope(requested_by=current_user.user_id, trace_context=_tc())
    await publisher.publish(SUBJECT_STEALER_CORPUS_REINDEX, env)
    await audit.emit(
        event="eyenet.audit.stealer_corpus.reindex_requested",
        subject_kind="stealer_corpus",
        system_user_id=current_user.user_id,
        payload={},
    )
    return StealerReindexResponse(queued=True)
