"""Round-trip and exhaustiveness tests for PersonaUpdatedEnvelope."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts._base import TraceContext
from eyenet.contracts.attribution import (
    SUBJECT_PERSONA_UPDATED,
    PersonaChangeKind,
    PersonaUpdatedEnvelope,
)

_TC = TraceContext(
    traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
)
_PID = UUID("00000000-0000-0000-0000-000000000010")
_A = UUID("00000000-0000-0000-0000-000000000001")
_B = UUID("00000000-0000-0000-0000-000000000002")
_LID = UUID("00000000-0000-0000-0000-000000000099")
_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)


def _make(kind: PersonaChangeKind, via: UUID | None = _LID) -> PersonaUpdatedEnvelope:
    return PersonaUpdatedEnvelope(
        persona_id=_PID,
        member_actor_ids=[_A, _B],
        change_kind=kind,
        via_linkage_id=via,
        at=_NOW,
        trace_context=_TC,
    )


@pytest.mark.contract
@pytest.mark.parametrize("kind", list(PersonaChangeKind))
def test_round_trip_all_kinds(kind: PersonaChangeKind) -> None:
    env = _make(kind)
    restored = PersonaUpdatedEnvelope.model_validate(env.model_dump())
    assert restored == env


@pytest.mark.contract
@pytest.mark.parametrize("kind", list(PersonaChangeKind))
def test_json_round_trip_all_kinds(kind: PersonaChangeKind) -> None:
    env = _make(kind)
    restored = PersonaUpdatedEnvelope.model_validate_json(env.model_dump_json())
    assert restored == env


@pytest.mark.contract
def test_change_kind_exhaustiveness() -> None:
    expected = {"created", "members_added", "members_removed", "merged_with", "split_from"}
    actual = {k.value for k in PersonaChangeKind}
    assert actual == expected, f"PersonaChangeKind missing values: {expected - actual}"


@pytest.mark.contract
def test_via_linkage_id_optional() -> None:
    env = _make(PersonaChangeKind.CREATED, via=None)
    assert env.via_linkage_id is None
    restored = PersonaUpdatedEnvelope.model_validate(env.model_dump())
    assert restored.via_linkage_id is None


@pytest.mark.contract
def test_subject_constant() -> None:
    assert SUBJECT_PERSONA_UPDATED == "attribution.persona.updated"


@pytest.mark.contract
def test_member_actor_ids_preserved() -> None:
    env = _make(PersonaChangeKind.MEMBERS_ADDED)
    assert set(env.member_actor_ids) == {_A, _B}


@pytest.mark.contract
def test_schema_version_present() -> None:
    env = _make(PersonaChangeKind.CREATED)
    assert env.schema_version
