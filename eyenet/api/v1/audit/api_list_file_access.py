# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit/file-access — signed exoneration record by content hash (§5.8).

Returns every journalled access served under ``content_hash``, plus a detached
server Ed25519 signature over the answer. An EMPTY access list is a POSITIVE
cryptographic assertion of non-access: nobody was served this content up to the
signed journal head. The signature binds the content hash, the journal head, the
query time, and the exact ordered set of returned access ids.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_exoneration_signer, get_storage
from eyenet.api.v1.audit._exoneration import journal_entry
from eyenet.api.v1.schemas.attachments import FileAccessExoneration
from eyenet.crypto import ExonerationSigner, build_exoneration_canonical
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])


@router.get(
    "/audit/file-access",
    operation_id="audit_file_access_by_hash",
    response_model=FileAccessExoneration,
    status_code=200,
)
async def audit_file_access_by_hash(
    storage: Annotated[BaseRepository, Depends(get_storage)],
    signer: Annotated[ExonerationSigner, Depends(get_exoneration_signer)],
    _: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    content_hash: str = Query(pattern=r"^[0-9a-f]{64}$"),
) -> FileAccessExoneration:
    content_hash_bytes = bytes.fromhex(content_hash)
    rows = await storage.list_file_access_by_content_hash(content_hash_bytes)
    head = await storage.file_access_journal_head()
    query_time = datetime.now(tz=UTC)
    canonical = build_exoneration_canonical(
        query_kind="by_hash",
        content_hash=content_hash_bytes,
        user_id=b"",
        since="",
        until="",
        query_time=query_time.isoformat(),
        journal_head=head,
        access_ids=[row.access_id.bytes for row in rows],
    )
    return FileAccessExoneration(
        content_hash=content_hash,
        query_time=query_time,
        journal_head_at_query=head.hex(),
        accesses=[journal_entry(row) for row in rows],
        exoneration_signature=signer.sign(canonical),
    )
