# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concurrency stress on ``StealerArtifactsReader``.

The whole point of the AsyncClient conversion was to kill the shared-client
crash the API hit when the drawer fired three parallel requests. These tests
exercise the async readers with high concurrency to prove there is no
leftover sync-in-async surface. ``_rows`` is stubbed with an async method
that sleeps briefly so overlap is real, not sequential.
"""

from __future__ import annotations

import asyncio

import pytest

from eyenet.stealer.query import ArtifactCardRow, StealerArtifactsReader

pytestmark = pytest.mark.unit

_SHA = "a" * 64


class _SlowReader(StealerArtifactsReader):
    """Simulates round-trip latency so parallel calls really interleave."""

    def __init__(self, delay_s: float = 0.01) -> None:
        self._db = "stealer"
        self._client = None
        self._delay = delay_s
        self._in_flight = 0
        self._max_in_flight = 0
        self._lock = asyncio.Lock()
        self._card_row = (
            _SHA,
            "v-01",
            "US",
            "aff-42",
            "1.0",
            17,
            203,
            1,
            1,
            1,
            0,
        )
        self._count_row = (1,)

    async def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[object, ...]]:
        async with self._lock:
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self._delay)
            if "count()" in sql:
                return [self._count_row]
            return [self._card_row]
        finally:
            async with self._lock:
                self._in_flight -= 1


async def test_20_parallel_list_cards_no_crash() -> None:
    """20 concurrent list_cards() calls complete without error."""
    r = _SlowReader(delay_s=0.02)
    results = await asyncio.gather(*(r.list_cards(page=1, limit=25) for _ in range(20)))
    assert len(results) == 20
    for rows, total, pages in results:
        assert total == 1
        assert pages == 1
        assert len(rows) == 1
        assert isinstance(rows[0], ArtifactCardRow)


async def test_concurrency_actually_overlaps() -> None:
    """Stub records in-flight counts to prove calls are NOT serialized.

    If the reader accidentally reintroduced a shared-lock / mutex path, every
    call would be sequential and max_in_flight would stay at 1. We assert
    overlap is real.
    """
    r = _SlowReader(delay_s=0.05)
    await asyncio.gather(*(r.list_cards(page=1, limit=10) for _ in range(10)))
    # Each list_cards fires 2 _rows calls (count + list). With 10 parallel
    # callers that's up to 20 in-flight _rows invocations.
    assert r._max_in_flight >= 2, (
        f"expected overlap, saw max_in_flight={r._max_in_flight}: "
        "readers may have accidentally serialized"
    )
