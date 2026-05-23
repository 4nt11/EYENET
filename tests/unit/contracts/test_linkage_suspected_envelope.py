"""Round-trip and ordering invariants for LinkageSuspectedEnvelope."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_LINKAGE_SUSPECTED,
    LinkageSuspectedEnvelope,
)

_TC = TraceContext(
    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
)
_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_LID = UUID("00000000-0000-0000-0000-000000000099")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)


def _make() -> LinkageSuspectedEnvelope:
    return LinkageSuspectedEnvelope.from_pair(
        _A,
        _B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        notes="flagged for review",
        trace_context=_TC,
    )


@pytest.mark.contract
def test_round_trip_json() -> None:
    env = _make()
    raw = env.model_dump_json()
    restored = LinkageSuspectedEnvelope.model_validate_json(raw)
    assert restored == env


@pytest.mark.contract
def test_round_trip_dict() -> None:
    env = _make()
    restored = LinkageSuspectedEnvelope.model_validate(env.model_dump())
    assert restored == env


@pytest.mark.contract
def test_actor_ordering_invariant() -> None:
    env = _make()
    assert env.actor_a_id < env.actor_b_id, "a<b invariant violated"


@pytest.mark.contract
def test_from_pair_auto_sorts() -> None:
    env = LinkageSuspectedEnvelope.from_pair(
        _B,
        _A,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        trace_context=_TC,
    )
    assert env.actor_a_id == _A
    assert env.actor_b_id == _B


@pytest.mark.contract
def test_rejects_reversed_pair_direct() -> None:
    with pytest.raises(ValueError, match="actor_a_id < actor_b_id"):
        LinkageSuspectedEnvelope(
            linkage_id=_LID,
            actor_a_id=_B,
            actor_b_id=_A,
            decided_by="anti",
            decided_at=_NOW,
            trace_context=_TC,
        )


@pytest.mark.contract
def test_subject_constant_present() -> None:
    assert SUBJECT_LINKAGE_SUSPECTED == "attribution.linkage.suspected"


@pytest.mark.contract
def test_schema_version_is_string() -> None:
    env = _make()
    assert isinstance(env.schema_version, str)
    assert env.schema_version


@pytest.mark.contract
def test_notes_optional() -> None:
    env = LinkageSuspectedEnvelope.from_pair(
        _A,
        _B,
        linkage_id=_LID,
        decided_by="anti",
        decided_at=_NOW,
        trace_context=_TC,
    )
    assert env.notes is None
