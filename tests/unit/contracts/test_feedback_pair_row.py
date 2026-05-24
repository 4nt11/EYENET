"""FeedbackPairRow contract — pair-order invariant + ground_truth enum + roundtrip."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.feedback import FeedbackPairRow

A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")
LINKAGE = UUID("00000000-0000-0000-0000-0000000000aa")


@pytest.mark.contract
def test_row_rejects_reversed_pair() -> None:
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        FeedbackPairRow(
            linkage_id=LINKAGE,
            actor_a_id=B,
            actor_b_id=A,
            ground_truth="same",
            decided_by="op",
            decided_at=datetime(2026, 5, 24, tzinfo=UTC),
        )


@pytest.mark.contract
def test_row_from_pair_auto_sorts() -> None:
    row = FeedbackPairRow.from_pair(
        B,
        A,
        linkage_id=LINKAGE,
        ground_truth="diff",
        decided_by="op",
        decided_at=datetime(2026, 5, 24, tzinfo=UTC),
    )
    assert row.actor_a_id == A
    assert row.actor_b_id == B
    assert row.ground_truth == "diff"


@pytest.mark.contract
def test_row_rejects_unknown_ground_truth() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="ground_truth"):
        FeedbackPairRow(
            linkage_id=LINKAGE,
            actor_a_id=A,
            actor_b_id=B,
            ground_truth="maybe",  # type: ignore[arg-type]
            decided_by="op",
            decided_at=datetime(2026, 5, 24, tzinfo=UTC),
        )


@pytest.mark.contract
def test_row_roundtrip_json() -> None:
    row = FeedbackPairRow(
        linkage_id=LINKAGE,
        actor_a_id=A,
        actor_b_id=B,
        ground_truth="same",
        decided_by="op",
        decided_at=datetime(2026, 5, 24, tzinfo=UTC),
        notes="confirmed via verifier",
    )
    payload = row.model_dump_json()
    revived = FeedbackPairRow.model_validate_json(payload)
    assert revived == row
