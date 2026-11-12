# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read schemas for the ULP corpus surface (stealer stats + credential search)."""

from __future__ import annotations

from ._base import ApiSchema


class StealerBucket(ApiSchema):
    """One (key, count) bar for a distribution chart."""

    key: str
    count: int


class StealerStatsResponse(ApiSchema):
    """Overview of the stealer-creds corpus for the dashboard charts + tiles.

    ``initialized`` is False when the ClickHouse `stealer.creds` table has not
    been created yet (no stealer channel has ever been ingested). In that case
    all counters are zero and the lists are empty; the dashboard should render
    a "connect a stealer channel" hint instead of empty charts.
    """

    initialized: bool = True
    total_creds: int
    unique_creds: int
    distinct_hosts: int
    by_scheme: list[StealerBucket]
    by_tld: list[StealerBucket]  # ccTLD of the service host (country-ish signal)
    top_hosts: list[StealerBucket]


class StealerCred(ApiSchema):
    """One credential row from a host search (read:stealer — full content)."""

    host: str
    url: str
    login: str
    password: str
    scheme: str
    tld: str


class StealerSearchResponse(ApiSchema):
    """A page of credential hits for a host search.

    ``initialized`` is False when the ClickHouse `stealer.creds` table has not
    been created yet; `items` is empty in that case. See `StealerStatsResponse`.
    """

    initialized: bool = True
    items: list[StealerCred]


__all__ = [
    "StealerBucket",
    "StealerCred",
    "StealerSearchResponse",
    "StealerStatsResponse",
]
