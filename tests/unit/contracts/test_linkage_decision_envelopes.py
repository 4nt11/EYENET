"""Round-trip and ordering invariants for LinkageConfirmedEnvelope and LinkageRejectedEnvelope."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_CONFIRMED,
    SUBJECT_LINKAGE_REJECTED,
    LinkageConfirmedEnvelope,
    LinkageRejectedEnvelope,
)

_TC = TraceContext(
    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
)
_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_LID = UUID("00000000-0000-0000-0000-000000000099")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)


def _confirmed() -> LinkageConfirmedEnvelope:
    return LinkageConfirmedEnvelope.from_pair(
        _A,
        _B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        notes="high confidence",
        trace_context=_TC,
    )


def _rejected() -> LinkageRejectedEnvelope:
    return LinkageRejectedEnvelope.from_pair(
        _A,
        _B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        notes="false positive",
        trace_context=_TC,
    )


@pytest.mark.contract
def test_confirmed_round_trip() -> None:
    env = _confirmed()
    restored = LinkageConfirmedEnvelope.model_validate(env.model_dump())
    assert restored == env


@pytest.mark.contract
def test_rejected_round_trip() -> None:
    env = _rejected()
    restored = LinkageRejectedEnvelope.model_validate(env.model_dump())
    assert restored == env


@pytest.mark.contract
def test_confirmed_json_round_trip() -> None:
    env = _confirmed()
    restored = LinkageConfirmedEnvelope.model_validate_json(env.model_dump_json())
    assert restored == env


@pytest.mark.contract
def test_rejected_json_round_trip() -> None:
    env = _rejected()
    restored = LinkageRejectedEnvelope.model_validate_json(env.model_dump_json())
    assert restored == env


@pytest.mark.contract
def test_confirmed_actor_ordering() -> None:
    env = _confirmed()
    assert env.actor_a_id < env.actor_b_id


@pytest.mark.contract
def test_rejected_actor_ordering() -> None:
    env = _rejected()
    assert env.actor_a_id < env.actor_b_id


@pytest.mark.contract
def test_confirmed_from_pair_auto_sorts() -> None:
    env = LinkageConfirmedEnvelope.from_pair(
        _B,
        _A,
        linkage_id=_LID,
        decided_by="op",
        decided_at=_NOW,
        trace_context=_TC,
    )
    assert env.actor_a_id == _A
    assert env.actor_b_id == _B


@pytest.mark.contract
def test_rejected_from_pair_auto_sorts() -> None:
    env = LinkageRejectedEnvelope.from_pair(
        _B,
        _A,
        linkage_id=_LID,
        decided_by="op",
        decided_at=_NOW,
        trace_context=_TC,
    )
    assert env.actor_a_id == _A
    assert env.actor_b_id == _B


@pytest.mark.contract
def test_confirmed_rejects_reversed_direct() -> None:
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        LinkageConfirmedEnvelope(
            linkage_id=_LID,
            actor_a_id=_B,
            actor_b_id=_A,
            decided_by="op",
            decided_at=_NOW,
            trace_context=_TC,
        )


@pytest.mark.contract
def test_rejected_rejects_reversed_direct() -> None:
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        LinkageRejectedEnvelope(
            linkage_id=_LID,
            actor_a_id=_B,
            actor_b_id=_A,
            decided_by="op",
            decided_at=_NOW,
            trace_context=_TC,
        )


@pytest.mark.contract
def test_subject_constants() -> None:
    assert SUBJECT_LINKAGE_CONFIRMED == "attribution.linkage.confirmed"
    assert SUBJECT_LINKAGE_REJECTED == "attribution.linkage.rejected"
