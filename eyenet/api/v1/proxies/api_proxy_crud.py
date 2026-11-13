# SPDX-License-Identifier: AGPL-3.0-or-later
"""Proxy-row CRUD + state flip + reveal (v1.2.0).

Nested under /v1/proxy-pools/{pool_id}/proxies for create + list; flat
/v1/proxies/{proxy_id} for get / delete / state. The nested shape mirrors
collectors <-> candidates: pool is the natural listing scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope, get_session_key, get_storage
from eyenet.contracts.enums import ProxyState
from eyenet.contracts.proxy import (
    ProxyAdminResponse,
    ProxyCreateRequest,
    ProxyResponse,
    ProxyStateUpdateRequest,
)
from eyenet.storage.repository import BaseRepository

from ._mask import to_proxy_admin_response, to_proxy_response

router = APIRouter(tags=["proxies"])


@router.post(
    "/proxy-pools/{pool_id}/proxies",
    operation_id="proxy_create",
    response_model=ProxyResponse,
    status_code=201,
)
async def proxy_create(
    pool_id: UUID,
    body: ProxyCreateRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:write"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    session_key: Annotated[object, Depends(get_session_key)],
) -> ProxyResponse:
    pool = await storage.get_proxy_pool(pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="proxy_pool not found")
    ciphertext: bytes | None = None
    if body.secret:
        # The dep returns an object type for ergonomic reasons; it is a Fernet.
        ciphertext = session_key.encrypt(body.secret.encode("utf-8"))  # type: ignore[attr-defined]
    row = await storage.create_proxy(
        pool_id=pool_id,
        kind=body.kind,
        host=body.host,
        port=body.port,
        secret_encrypted=ciphertext,
        source=body.source,
        notes=body.notes,
        created_at=datetime.now(tz=UTC).replace(tzinfo=None),
    )
    return to_proxy_response(row)


@router.get(
    "/proxy-pools/{pool_id}/proxies",
    operation_id="proxy_list",
    response_model=list[ProxyResponse],
)
async def proxy_list(
    pool_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:read"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    state: Annotated[ProxyState | None, Query()] = None,
) -> list[ProxyResponse]:
    rows = await storage.list_proxies(pool_id=pool_id, state=state)
    return [to_proxy_response(r) for r in rows]


@router.get(
    "/proxies/{proxy_id}",
    operation_id="proxy_get",
    # response_model declared dynamically via union; we return either shape.
)
async def proxy_get(
    proxy_id: UUID,
    current_user: Annotated[CurrentUser, Depends(RequireScope("proxy:read"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    session_key: Annotated[object, Depends(get_session_key)],
    reveal: Annotated[bool, Query(description="Include decrypted secret. Requires proxy:admin.")] = False,
) -> ProxyAdminResponse | ProxyResponse:
    row = await storage.get_proxy(proxy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="proxy not found")
    if not reveal:
        return to_proxy_response(row)
    if "proxy:admin" not in current_user.effective_scopes:
        raise HTTPException(
            status_code=403,
            detail="reveal=true requires the proxy:admin capability",
        )
    return to_proxy_admin_response(row, session_key)  # type: ignore[arg-type]


@router.delete(
    "/proxies/{proxy_id}",
    operation_id="proxy_delete",
    status_code=204,
)
async def proxy_delete(
    proxy_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:write"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> None:
    deleted = await storage.delete_proxy(proxy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="proxy not found")


@router.post(
    "/proxies/{proxy_id}/state",
    operation_id="proxy_update_state",
    response_model=ProxyResponse,
)
async def proxy_update_state(
    proxy_id: UUID,
    body: ProxyStateUpdateRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:write"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ProxyResponse:
    row = await storage.update_proxy_state(
        proxy_id,
        state=body.state,
        last_error=body.reason,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="proxy not found")
    return to_proxy_response(row)
