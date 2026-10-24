# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/search — credential search over the ULP corpus (read:stealer).

Substring search on host (ILIKE, parameterized), paginated. Returns full credential
content — that's the point of the corpus, and read:stealer (an expiring clearance scope)
is the gate. A corpus that's down is a 503.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import StealerCred, StealerSearchResponse
from eyenet.stealer.query import StealerCredsReader

router = APIRouter(tags=["stealer"])
_reader = StealerCredsReader()


@router.get(
    "/stealer/search",
    operation_id="stealer_search",
    response_model=StealerSearchResponse,
    status_code=200,
)
async def stealer_search(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    host: Annotated[
        str | None, Query(description="Case-insensitive substring over the credential host.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StealerSearchResponse:
    try:
        rows = await asyncio.to_thread(
            lambda: _reader.search(host=host, limit=limit, offset=offset)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerSearchResponse(
        items=[
            StealerCred(
                host=r.host, url=r.url, login=r.login,
                password=r.password, scheme=r.scheme, tld=r.tld,
            )
            for r in rows
        ]
    )
