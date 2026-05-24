"""Graph aggregate stats.

`GraphStats` is pure aggregation — produced by the route layer from counts
across `actor`, `persona`, `linkage`, and `observation` tables. No
`from_domain` because the inputs are scalars, not a single row.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — GraphStats.
API_PLAN §3.2.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ._base import ApiSchema


class LinkageStateCounts(ApiSchema):
    """Per-state counters surfaced inside `GraphStats`."""

    proposed: int = Field(ge=0)
    suspected: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    rejected: int = Field(ge=0)


class GraphStats(ApiSchema):
    """200 response for `GET /v1/graph/stats`."""

    actors: int = Field(ge=0)
    personas: int = Field(ge=0)
    linkages: LinkageStateCounts
    observations: int = Field(ge=0)
    computed_at: datetime


__all__ = ["GraphStats", "LinkageStateCounts"]
