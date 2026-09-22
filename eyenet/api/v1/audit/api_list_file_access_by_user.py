# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit/file-access/by-user — per-operator access history (§5.8).

Returns every journalled access served to ``user_id`` within an optional
``[since, until]`` window, plus a detached server Ed25519 signature. An EMPTY
list is a POSITIVE assertion that this operator was served nothing in the window.

The envelope has no user field, so ``content_hash`` carries the by-user sentinel
(all-zero hex). The SIGNATURE, however, binds the real ``user_id`` + window (not
the sentinel): a verifier reconstructs the canonical from their own query
parameters, so operator B can never replay operator A's signed non-access
assertion as their own. See :mod:`eyenet.crypto._exoneration_signing`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_exoneration_signer, get_storage
from eyenet.api.v1.audit._exoneration import journal_entry
from eyenet.api.v1.schemas.attachments import FileAccessExoneration
from eyenet.crypto import (
    BY_USER_CONTENT_HASH_SENTINEL,
    ExonerationSigner,
    build_exoneration_canonical,
)
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/file-access/by-user",
    operation_id="audit_file_access_by_user",
    response_model=FileAccessExoneration,
    status_code=200,
)
async def audit_file_access_by_user(
    storage: Annotated[BaseRepository, Depends(get_storage)],
    signer: Annotated[ExonerationSigner, Depends(get_exoneration_signer)],
    _: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    user_id: UUID = Query(...),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
) -> FileAccessExoneration:
    rows = await storage.list_file_access_by_user(user_id, since=since, until=until)
    head = await storage.file_access_journal_head()
    query_time = datetime.now(tz=UTC)
    canonical = build_exoneration_canonical(
        query_kind="by_user",
        content_hash=b"",
        user_id=user_id.bytes,
        since=since.isoformat() if since is not None else "",
        until=until.isoformat() if until is not None else "",
        query_time=query_time.isoformat(),
        journal_head=head,
        access_ids=[row.access_id.bytes for row in rows],
    )
    return FileAccessExoneration(
        content_hash=BY_USER_CONTENT_HASH_SENTINEL,
        query_time=query_time,
        journal_head_at_query=head.hex(),
        accesses=[journal_entry(row) for row in rows],
        exoneration_signature=signer.sign(canonical),
    )
