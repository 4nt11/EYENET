# SPDX-License-Identifier: AGPL-3.0-or-later
"""PATCH /v1/identities/{identity_id}/proxy (v1.2.0).

Attach or detach a proxy pool for an identity and flip the sticky flag.
Dual-scope: :scope:`proxy:write` (pool side) + :scope:`write:identity`
(identity side). Both scopes live on admin + analyst baselines so the
normal operator path is uninterrupted.

Detaching (``pool_id=None``) releases any sticky binding this identity
held, so the proxies rejoin the lease pool automatically.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.contracts.identity import IdentityRow
from eyenet.contracts.proxy import IdentityProxyBindRequest
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["identities"])


@router.patch(
    "/identities/{identity_id}/proxy",
    operation_id="identity_bind_proxy",
    response_model=IdentityRow,
)
async def identity_bind_proxy(
    identity_id: UUID,
    body: IdentityProxyBindRequest,
    current_user: Annotated[CurrentUser, Depends(RequireScope("proxy:write"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> IdentityRow:
    # Dual-scope: proxy:write (above) + write:identity (here) so we never
    # modify identity state on a caller holding only pool-management scope.
    if "write:identity" not in current_user.effective_scopes:
        raise HTTPException(
            status_code=403,
            detail="identity-side change requires the write:identity scope",
        )
    if body.pool_id is not None:
        pool = await storage.get_proxy_pool(body.pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail="proxy_pool not found")
    row = await storage.bind_identity_proxy_pool(
        identity_id,
        pool_id=body.pool_id,
        sticky=body.sticky,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="identity not found")
    return row
