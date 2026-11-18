# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-driven reclassify endpoints.

- POST /v1/stealer/artifacts/{sha}/{folder}/reclassify (write:stealer):
  recompute + persist ONE verdict against the current catalog.
  Synchronous, fast (two cheap CH queries + score). Returns the new
  verdict for the drawer to re-render in place.

- POST /v1/stealer/reclassify (admin:stealer): kick a background corpus
  sweep via the bus (SUBJECT_STEALER_CORPUS_RECLASSIFY). Returns 202
  with a queued-ok envelope; completion arrives in the processor's log
  + updated victim_family_verdict rows.

Both audit explicitly. The single-victim endpoint also lets the
operator override step (PUT family-override) fall through to the
classifier again when the operator later clears the override.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_publisher
from eyenet.api.v1.schemas.stealer import (
    StealerFamilyRunnerUp,
    StealerFamilyVerdict,
    StealerReclassifyCorpusResponse,
)
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.contracts._base import TraceContext
from eyenet.contracts.stealer_events import (
    SUBJECT_STEALER_CORPUS_RECLASSIFY,
    StealerCorpusReclassifyEnvelope,
)
from eyenet.stealer.classifier import classify
from eyenet.stealer.classifier_io import collect_evidence, write_verdict_sync
from eyenet.stealer.clickhouse import (
    FileAuditSink,
    get_async_clickhouse_client,
    get_clickhouse_client,
)
from eyenet.stealer.query import StealerCorpusUninitializedError
from eyenet.telemetry.audit import AuditEmitter
from eyenet.telemetry.propagation import ZERO_TRACEPARENT, current_traceparent

router = APIRouter(tags=["stealer"])


@router.post(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}/reclassify",
    operation_id="stealer_artifact_reclassify",
    response_model=StealerFamilyVerdict,
    status_code=200,
)
async def stealer_artifact_reclassify(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerFamilyVerdict:
    """Recompute + persist the verdict for ONE victim. Synchronous."""
    try:
        async_client = await get_async_clickhouse_client()
        FileAuditSink().ensure_schema()
        evidence = await collect_evidence(async_client, archive_sha256, victim_folder)
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    result = classify(evidence)
    # Sync write: a one-row insert is cheap enough to block the handler.
    write_verdict_sync(get_clickhouse_client(), archive_sha256, victim_folder, result)
    await audit.emit(
        event="eyenet.audit.stealer_artifact.reclassify",
        subject_kind="stealer_artifact",
        system_user_id=current_user.user_id,
        payload={
            "archive_sha256": archive_sha256,
            "victim_folder": victim_folder,
            "slug": result.verdict.slug if result.verdict else "",
            "confidence": result.verdict.confidence if result.verdict else 0.0,
        },
    )
    slug = result.verdict.slug if result.verdict else ""
    confidence = result.verdict.confidence if result.verdict else 0.0
    evidence_tokens = list(result.verdict.evidence) if result.verdict else []
    return StealerFamilyVerdict(
        slug=slug,
        confidence=confidence,
        evidence=evidence_tokens,
        runners_up=[
            StealerFamilyRunnerUp(slug=r.slug, confidence=r.confidence) for r in result.runners_up
        ],
    )


@router.post(
    "/stealer/reclassify",
    operation_id="stealer_corpus_reclassify",
    response_model=StealerReclassifyCorpusResponse,
    status_code=202,
)
async def stealer_corpus_reclassify(
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:stealer"))],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerReclassifyCorpusResponse:
    """Kick a full-corpus reclassify sweep on the stealer-processor via
    the bus. Returns 202 immediately; completion arrives in the
    processor's log + verdict table rows. admin:stealer gated."""
    env = StealerCorpusReclassifyEnvelope(
        requested_by=current_user.user_id,
        trace_context=TraceContext(traceparent=current_traceparent() or ZERO_TRACEPARENT),
    )
    await publisher.publish(SUBJECT_STEALER_CORPUS_RECLASSIFY, env)
    await audit.emit(
        event="eyenet.audit.stealer_corpus.reclassify_requested",
        subject_kind="stealer_corpus",
        system_user_id=current_user.user_id,
        payload={},
    )
    return StealerReclassifyCorpusResponse(queued=True)
