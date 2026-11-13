# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/proxy-pools/{pool_id}/proxies/bulk (v1.2.0).

Paste a textarea of proxy lines, we parse, Fernet-encrypt each credential,
and bulk-insert into the pool. Entries that collide on (host, port, kind)
are skipped (not an error); malformed lines are collected and returned so
the operator sees exactly which paste lines to fix.

:scope:`proxy:admin` only: this is the primary path for daily-dumped paste
material and we want the credential-visibility review attached to the same
scope that granted the pool itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope, get_session_key, get_storage
from eyenet.contracts.proxy import ProxyBulkCreateRequest, ProxyBulkCreateResult
from eyenet.storage.repository import BaseRepository

from ._parse_bulk import parse_bulk_lines

router = APIRouter(tags=["proxies"])


@router.post(
    "/proxy-pools/{pool_id}/proxies/bulk",
    operation_id="proxy_bulk_create",
    response_model=ProxyBulkCreateResult,
    status_code=201,
)
async def proxy_bulk_create(
    pool_id: UUID,
    body: ProxyBulkCreateRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:admin"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    session_key: Annotated[object, Depends(get_session_key)],
) -> ProxyBulkCreateResult:
    pool = await storage.get_proxy_pool(pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="proxy_pool not found")

    parsed = parse_bulk_lines(body.lines, default_kind=body.default_kind)
    entries: list[dict[str, object]] = []
    for entry in parsed.entries:
        ciphertext: bytes | None = None
        if entry.secret:
            ciphertext = session_key.encrypt(entry.secret.encode("utf-8"))  # type: ignore[attr-defined]
        entries.append(
            {
                "kind": entry.kind,
                "host": entry.host,
                "port": entry.port,
                "secret_encrypted": ciphertext,
                "source": body.source,
                "notes": None,
            }
        )

    rejected = list(parsed.rejected)
    result = {"inserted": 0, "skipped_duplicate": 0, "skipped_keys": []}
    if entries:
        result = await storage.bulk_create_proxies(
            pool_id=pool_id,
            entries=entries,
            created_at=datetime.now(tz=UTC),
        )
        # Surface duplicates to the operator in the rejection stream too so
        # the UI can render one unified list.
        for key in result.get("skipped_keys", []):  # type: ignore[union-attr]
            rejected.append(f"duplicate (host:port:kind): {key}")
    return ProxyBulkCreateResult(
        inserted=int(result.get("inserted", 0)),
        skipped_duplicate=int(result.get("skipped_duplicate", 0)),
        rejected=rejected,
    )
