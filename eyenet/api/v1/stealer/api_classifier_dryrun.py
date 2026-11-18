# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/stealer/families/classify-dryrun.

Operator-proposed signal edits for one or more families, scored across
a bounded sample of the corpus alongside the current on-disk catalog.
Returns per-slug (before, after) counts + a list of per-victim verdict
shifts.

Scope: read:stealer. The dry-run is strictly read-only; no writes to
the verdict table, no writes to the family catalog. A commit of the
tested signals is a subsequent PUT /stealer/families/{slug}
(write:stealer).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope, get_audit
from eyenet.api.v1.schemas.stealer import (
    StealerClassifierCountDelta,
    StealerClassifierDryRunRequest,
    StealerClassifierDryRunResponse,
    StealerClassifierVictimShift,
)
from eyenet.stealer.classifier_dryrun import dry_run
from eyenet.stealer.families.rw import _validate_family_shape
from eyenet.stealer.query import StealerCorpusUninitializedError
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["stealer"])


@router.post(
    "/stealer/families/classify-dryrun",
    operation_id="stealer_classifier_dryrun",
    response_model=StealerClassifierDryRunResponse,
    status_code=200,
)
async def stealer_classifier_dryrun(
    body: StealerClassifierDryRunRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StealerClassifierDryRunResponse:
    # Validate every proposed family through the same loader rules used
    # for a real catalog write. A bad signal payload here would not be
    # catastrophic (the scorer is defensive), but failing loud mirrors
    # what the operator will see on save, so the dry run reflects
    # reality.
    for fam in body.families:
        try:
            _validate_family_shape(fam)
        except ValueError as exc:
            raise HTTPException(422, f"invalid family payload: {exc}") from exc
    try:
        result = await dry_run(body.families, limit=body.limit)
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    # The dry-run reads evidence out of the ClickHouse corpus (file_audit
    # + extracted_records) across up to _DRYRUN_HARD_CAP victims, which
    # is a non-trivial corpus read even though no persisted verdicts
    # change. Emit an explicit audit event so the access + the proposed
    # family shape are non-repudiable under the write:stealer-adjacent
    # tuning workflow.
    await audit.emit(
        event="eyenet.audit.stealer_classifier.dryrun",
        subject_kind="stealer_classifier",
        system_user_id=current_user.user_id,
        payload={
            "limit": body.limit,
            "sampled": result.sampled,
            "proposed_slugs": [str(f.get("slug", "")) for f in body.families if f.get("slug")],
            "moves": len(result.shifts),
        },
    )
    return StealerClassifierDryRunResponse(
        sampled=result.sampled,
        counts=[
            StealerClassifierCountDelta(slug=c.slug, before=c.before, after=c.after)
            for c in result.counts
        ],
        shifts=[
            StealerClassifierVictimShift(
                archive_sha256=s.archive_sha256,
                victim_folder=s.victim_folder,
                before_slug=s.before_slug,
                before_confidence=s.before_confidence,
                after_slug=s.after_slug,
                after_confidence=s.after_confidence,
            )
            for s in result.shifts
        ],
    )
