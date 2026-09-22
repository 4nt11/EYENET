# SPDX-License-Identifier: AGPL-3.0-or-later
"""record_verifier_result / get_verifier_result (FeedbackMixin, M8 surfacing)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_record_and_get(storage: BaseRepository) -> None:
    lid = uuid4()
    await storage.record_verifier_result(
        linkage_id=lid, composite=0.83, floor=0.60, state="suspected",
        results=[{"method": "compression_distance", "score": 0.81, "confidence": 1.0,
                  "skipped": False, "detail": "NCD 0.19"}],
        computed_at=_NOW,
    )
    row = await storage.get_verifier_result(lid)
    assert row is not None
    assert row.composite == 0.83  # type: ignore[attr-defined]
    assert row.state == "suspected"  # type: ignore[attr-defined]
    assert row.results[0]["method"] == "compression_distance"  # type: ignore[attr-defined]


async def test_record_is_idempotent_on_linkage(storage: BaseRepository) -> None:
    lid = uuid4()
    await storage.record_verifier_result(
        linkage_id=lid, composite=0.5, floor=0.6, state="below_floor",
        results=[], computed_at=_NOW,
    )
    await storage.record_verifier_result(
        linkage_id=lid, composite=0.7, floor=0.6, state="suspected",
        results=[], computed_at=_NOW,
    )
    row = await storage.get_verifier_result(lid)
    assert row.composite == 0.7  # type: ignore[attr-defined]
    assert row.state == "suspected"  # type: ignore[attr-defined]


async def test_get_missing_returns_none(storage: BaseRepository) -> None:
    assert await storage.get_verifier_result(uuid4()) is None
