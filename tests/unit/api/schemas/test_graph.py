"""Shape tests for GraphStats + LinkageStateCounts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import GraphStats, LinkageStateCounts

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


def test_graph_stats_happy(now: datetime) -> None:
    stats = GraphStats(
        actors=10,
        personas=2,
        linkages=LinkageStateCounts(proposed=1, suspected=2, confirmed=3, rejected=0),
        observations=100,
        computed_at=now,
    )
    assert stats.linkages.confirmed == 3


@pytest.mark.parametrize("field", ["proposed", "suspected", "confirmed", "rejected"])
def test_linkage_state_counts_required(field: str) -> None:
    payload = {"proposed": 0, "suspected": 0, "confirmed": 0, "rejected": 0}
    del payload[field]
    with pytest.raises(PydanticValidationError):
        LinkageStateCounts.model_validate(payload)


def test_linkage_state_counts_non_negative() -> None:
    with pytest.raises(PydanticValidationError):
        LinkageStateCounts(proposed=-1, suspected=0, confirmed=0, rejected=0)


def test_graph_stats_rejects_extra(now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        GraphStats.model_validate(
            {
                "actors": 1,
                "personas": 1,
                "linkages": {"proposed": 0, "suspected": 0, "confirmed": 0, "rejected": 0},
                "observations": 1,
                "computed_at": now.isoformat(),
                "leaked": "value",
            },
        )
