# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read schemas for the ULP corpus surface (stealer stats + credential search)."""

from __future__ import annotations

from ._base import ApiSchema


class StealerBucket(ApiSchema):
    """One (key, count) bar for a distribution chart."""

    key: str
    count: int


class StealerStatsResponse(ApiSchema):
    """Overview of the stealer-creds corpus for the dashboard charts + tiles."""

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
    """A page of credential hits for a host search."""

    items: list[StealerCred]


__all__ = [
    "StealerBucket",
    "StealerCred",
    "StealerSearchResponse",
    "StealerStatsResponse",
]
