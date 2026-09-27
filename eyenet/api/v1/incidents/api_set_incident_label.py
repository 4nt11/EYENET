# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/incidents/{message_id}/labels — operator ground-truth relabel.

Analyst-grade triage (``write:incidents``). The classifier's prediction (the append-only
``incident`` row) is left untouched; this records the operator's TRUE label set for the
message in a separate channel. The pair (prediction, correction) is the retraining signal.
An empty ``labels`` means "false positive: none of these apply". Synchronous + audited.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from eyenet.api.deps import CurrentUser, RequireScope, UnprocessableError, get_audit, get_storage
from eyenet.api.v1.schemas.incidents import IncidentLabelOut, IncidentLabelUpdate
from eyenet.contracts.incident import IncidentLabelRow
from eyenet.incidents import rules
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["incidents"])

WRITE_SCOPE = "write:incidents"


@router.put(
    "/incidents/{message_id}/labels",
    operation_id="set_incident_label",
    response_model=IncidentLabelOut,
    status_code=200,
)
async def set_incident_label(
    message_id: UUID,
    body: IncidentLabelUpdate,
    current_user: Annotated[CurrentUser, Depends(RequireScope(WRITE_SCOPE))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    idempotency_key: Annotated[  # noqa: ARG001 — read by IdempotencyMiddleware; declared for OpenAPI
        str | None, Header(alias="Idempotency-Key", max_length=128)
    ] = None,
) -> IncidentLabelOut:
    bad = [lbl for lbl in body.labels if lbl not in rules.TAXONOMY_LABELS]
    if bad:
        raise UnprocessableError(
            f"unknown taxonomy label(s) {bad}; must be from {sorted(rules.TAXONOMY_LABELS)}"
        )
    row = cast(
        "IncidentLabelRow",
        await storage.set_incident_label(
            message_id,
            list(dict.fromkeys(body.labels)),  # dedup, preserve order
            decided_by=current_user.username,
            reason=body.reason,
            decided_at=datetime.now(tz=UTC),
        ),
    )
    await audit.emit(
        event="eyenet.audit.incident.relabeled",
        subject_kind="message",
        subject_id=message_id,
        system_user_id=current_user.user_id,
        payload={"labels": row.labels, "reason": row.reason},
    )
    return IncidentLabelOut(
        message_id=row.message_id,
        labels=row.labels,
        reason=row.reason,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
    )
