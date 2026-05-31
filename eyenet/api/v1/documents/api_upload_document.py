# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/documents — upload + classify one document (M10 slice 7).

The document is the RAW request body (``--data-binary``), not multipart: the
classifier wants the exact bytes for the host-side custody hash, and a raw body
avoids a form-encoding dependency. ``Content-Type`` records the client-claimed
mime; the optional ``X-Filename`` header records the original name (both are
evidence, neither is trusted for routing — the sandbox sniffs the real type).

The full deterministic pipeline runs synchronously (``ingest_document``) and the
SETTLED tier is persisted + audited before the 201 returns. Requires the
``write:documents`` scope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from eyenet.api.deps import CurrentUser, RequireScope, get_audit, get_data_dir, get_storage
from eyenet.api.v1.schemas.documents import DocumentUploadResult
from eyenet.classifier.ingest import ingest_document
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["documents"])


@router.post(
    "/documents",
    operation_id="documents_upload",
    response_model=DocumentUploadResult,
    status_code=201,
)
async def documents_upload(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:documents"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    x_filename: Annotated[str | None, Header()] = None,
) -> DocumentUploadResult:
    blob = await request.body()
    result = await ingest_document(
        blob,
        storage=storage,
        data_dir=data_dir,
        audit=audit,
        uploaded_by=current_user.user_id,
        filename=x_filename,
        mime=request.headers.get("content-type"),
    )
    return DocumentUploadResult(
        document_id=result.document_id,
        tier=result.verdict.tier,
        sha256=result.sha256,
        review_required=bool(result.verdict.review_flags),
    )
