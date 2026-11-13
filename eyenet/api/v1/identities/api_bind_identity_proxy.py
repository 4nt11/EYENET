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

from eyenet.api.deps import CurrentUser, RequireScope, get_bus, get_storage
from eyenet.contracts.bus import Bus
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import CollectorObservedState
from eyenet.contracts.identity import IdentityRow
from eyenet.contracts.proxy import IdentityProxyBindRequest
from eyenet.contracts.supervisor import RebindProxyCommand, command_subject_for
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
    bus: Annotated[Bus, Depends(get_bus)],
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

    # Signal the running collector (if any) to re-lease + rebuild its client
    # against the new pool binding. Stopped collectors pick it up at their
    # next start naturally. Best-effort: a bus hiccup does NOT fail the write.
    collector = await storage.get_collector_by_identity(identity_id)
    if collector is not None and collector.observed_state is CollectorObservedState.RUNNING:
        try:
            instance_id = compute_instance_id(row.name, collector.kind)
            cmd = RebindProxyCommand(identity_id=identity_id)
            await bus.publish(
                command_subject_for(instance_id),
                cmd.model_dump_json().encode("utf-8"),
                headers={"command-kind": cmd.kind},
            )
        except Exception:  # noqa: BLE001 - bus is best-effort for the signal
            pass
    return row
