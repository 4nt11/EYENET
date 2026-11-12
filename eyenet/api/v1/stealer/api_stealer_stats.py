# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/stats — corpus overview for the ULP dashboard (read:stealer).

Totals + distributions (scheme, ccTLD, top hosts) for the stat tiles + charts. Reads
the ClickHouse creds corpus off the event loop (clickhouse-connect is sync); a corpus
that's down (stealer profile not up) is a 503, not a 500.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import StealerBucket, StealerStatsResponse
from eyenet.stealer.query import Bucket, StealerCorpusUninitializedError, StealerCredsReader

router = APIRouter(tags=["stealer"])
_reader = StealerCredsReader()


def _buckets(xs: Iterable[Bucket]) -> list[StealerBucket]:
    return [StealerBucket(key=x.key, count=x.count) for x in xs]


@router.get(
    "/stealer/stats",
    operation_id="stealer_stats",
    response_model=StealerStatsResponse,
    status_code=200,
)
async def stealer_stats(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerStatsResponse:
    try:
        s = await asyncio.to_thread(_reader.stats)
    except StealerCorpusUninitializedError:
        # CH is up, the corpus just does not exist yet (no stealer channel ever
        # ingested). Return the zeroed response with initialized=False so the
        # dashboard can render an operator hint instead of a 503.
        return StealerStatsResponse(
            initialized=False,
            total_creds=0, unique_creds=0, distinct_hosts=0,
            by_scheme=[], by_tld=[], top_hosts=[],
        )
    except Exception as exc:  # CH unreachable / stealer profile down
        raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc
    return StealerStatsResponse(
        total_creds=s.total_creds,
        unique_creds=s.unique_creds,
        distinct_hosts=s.distinct_hosts,
        by_scheme=_buckets(s.by_scheme),
        by_tld=_buckets(s.by_tld),
        top_hosts=_buckets(s.top_hosts),
    )
