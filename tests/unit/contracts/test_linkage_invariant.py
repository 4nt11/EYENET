"""MODELS §2.5 / PLAN §5.2 — Linkage pair is unordered, stored a<b."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import LinkageProposedEnvelope, LinkageRow

A = UUID("00000000-0000-0000-0000-000000000001")
B = UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.contract
def test_row_rejects_reversed_pair() -> None:
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        LinkageRow(
            actor_a_id=B,
            actor_b_id=A,
            method="manual",
            score=0.5,
            proposed_at=datetime(2026, 5, 4, tzinfo=UTC),
        )


@pytest.mark.contract
def test_row_from_pair_auto_sorts() -> None:
    row = LinkageRow.from_pair(
        B,
        A,
        method="manual",
        score=0.5,
        evidence={},
        proposed_at=datetime(2026, 5, 4, tzinfo=UTC),
    )
    assert row.actor_a_id == A
    assert row.actor_b_id == B


@pytest.mark.contract
def test_envelope_rejects_reversed_pair() -> None:
    tc = TraceContext(
        traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    )
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        LinkageProposedEnvelope(
            linkage_id=UUID("00000000-0000-0000-0000-000000000099"),
            actor_a_id=B,
            actor_b_id=A,
            method="manual",
            score=0.5,
            proposed_at=datetime(2026, 5, 4, tzinfo=UTC),
            trace_context=tc,
        )
