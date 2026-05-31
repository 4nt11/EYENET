# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/documents — upload one document for ASYNC classification (M10 slice 8).

The document is the RAW request body (``--data-binary``), not multipart: the
classifier wants the exact bytes for the host-side custody hash, and a raw body
avoids a form-encoding dependency. ``Content-Type`` records the client-claimed
mime; the optional ``X-Filename`` header records the original name (both are
evidence, neither is trusted for routing — the sandbox sniffs the real type).

Classification is ASYNC (CLASSIFIER_PLAN §5): the endpoint stores the bytes +
persists a PROVISIONAL CLASSIFIED row (fail-closed — nothing below clearance is
served before settling) and publishes ``classify.document.uploaded`` for the
ClassifierService to settle the tier OFF the request path. Returns **202** with
the provisional tier. Requires the ``write:documents`` scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from eyenet.api.deps import CurrentUser, RequireScope, get_data_dir, get_publisher, get_storage
from eyenet.api.v1.schemas.documents import DocumentUploadResult
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.classifier.ingest import stage_document
from eyenet.contracts._base import TraceContext
from eyenet.contracts.classify_events import SUBJECT_DOCUMENT_UPLOADED, DocumentUploadedEnvelope
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.propagation import current_traceparent

router = APIRouter(tags=["documents"])

_ZERO_TRACEPARENT = "00-" + "0" * 32 + "-" + "0" * 16 + "-00"


@router.post(
    "/documents",
    operation_id="documents_upload",
    response_model=DocumentUploadResult,
    status_code=202,
)
async def documents_upload(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:documents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    publisher: Annotated[BusEnvelopePublisher, Depends(get_publisher)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    x_filename: Annotated[str | None, Header()] = None,
) -> DocumentUploadResult:
    blob = await request.body()
    document_id, sha256 = await stage_document(
        blob,
        storage=storage,
        data_dir=data_dir,
        uploaded_by=current_user.user_id,
        filename=x_filename,
        mime=request.headers.get("content-type"),
    )
    await publisher.publish(
        SUBJECT_DOCUMENT_UPLOADED,
        DocumentUploadedEnvelope(
            document_id=document_id,
            trace_context=TraceContext(traceparent=current_traceparent() or _ZERO_TRACEPARENT),
        ),
    )
    # Provisional: the row is born CLASSIFIED and the ClassifierService settles
    # the real tier asynchronously (fail-closed until then, §0).
    return DocumentUploadResult(
        document_id=document_id,
        tier=SensitivityTier.CLASSIFIED,
        sha256=sha256,
        review_required=False,
    )
