# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST / GET / PATCH / DELETE /v1/proxy-pools (v1.2.0).

Pool-level operations. `create` + `delete` require ``proxy:admin`` (they
reshape operator infra); list/get/update are ``proxy:write`` for the patch
and ``proxy:read`` for the readers.

Duplicate names surface as 409 via the app's :class:`IntegrityError` handler.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.contracts.proxy import (
    ProxyPoolCreateRequest,
    ProxyPoolRow,
    ProxyPoolUpdateRequest,
)
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["proxies"])


@router.post(
    "/proxy-pools",
    operation_id="proxy_pool_create",
    response_model=ProxyPoolRow,
    status_code=201,
)
async def proxy_pool_create(
    body: ProxyPoolCreateRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("proxy:admin"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ProxyPoolRow:
    return await storage.create_proxy_pool(
        name=body.name,
        kind_hint=body.kind_hint,
        description=body.description,
        created_at=datetime.now(tz=UTC).replace(tzinfo=None),
        created_by_user_id=current_user.user_id,
    )


@router.get(
    "/proxy-pools",
    operation_id="proxy_pool_list",
    response_model=list[ProxyPoolRow],
)
async def proxy_pool_list(
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:read"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[ProxyPoolRow]:
    return await storage.list_proxy_pools()


@router.get(
    "/proxy-pools/{pool_id}",
    operation_id="proxy_pool_get",
    response_model=ProxyPoolRow,
)
async def proxy_pool_get(
    pool_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:read"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ProxyPoolRow:
    row = await storage.get_proxy_pool(pool_id)
    if row is None:
        raise HTTPException(status_code=404, detail="proxy_pool not found")
    return row


@router.patch(
    "/proxy-pools/{pool_id}",
    operation_id="proxy_pool_update",
    response_model=ProxyPoolRow,
)
async def proxy_pool_update(
    pool_id: UUID,
    body: ProxyPoolUpdateRequest,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:write"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> ProxyPoolRow:
    row = await storage.update_proxy_pool(
        pool_id,
        name=body.name,
        kind_hint=body.kind_hint,
        description=body.description,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="proxy_pool not found")
    return row


@router.delete(
    "/proxy-pools/{pool_id}",
    operation_id="proxy_pool_delete",
    status_code=204,
)
async def proxy_pool_delete(
    pool_id: UUID,
    _: Annotated[CurrentUser, Depends(RequireScope("proxy:admin"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> None:
    try:
        deleted = await storage.delete_proxy_pool(pool_id)
    except ValueError as exc:
        # Pool is non-empty - 409 reads as "you must drain members first".
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="proxy_pool not found")
