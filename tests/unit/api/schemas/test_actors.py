"""Shape tests for actor-resource schemas + discriminated-union NeighborEdge."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    ActorDetail,
    ActorSummary,
    BelongsToPersonaAttrs,
    BelongsToPersonaEdge,
    LinkageState,
    LinkedToAttrs,
    LinkedToEdge,
    NeighborEdge,
    NeighborList,
    ObservationSummary,
    SensitivityTier,
    TimelineEntry,
)

pytestmark = pytest.mark.contract


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


@pytest.fixture
def uid2() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000002")


def test_actor_summary_happy(uid: UUID) -> None:
    summary = ActorSummary(actor_id=uid, primary_handle="@anti", platforms=["telegram"])
    assert summary.score is None


def test_actor_summary_rejects_extra(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        ActorSummary.model_validate(
            {"actor_id": str(uid), "primary_handle": "@x", "leak": "yes"},
        )


def test_actor_detail_extends_summary(uid: UUID, now: datetime) -> None:
    detail = ActorDetail(
        actor_id=uid,
        primary_handle="@anti",
        platforms=["telegram", "matrix"],
        first_seen=now,
        last_seen=now,
        alias_count=3,
        observation_count=100,
    )
    assert detail.alias_count == 3
    assert detail.persona_id is None


def test_actor_detail_requires_seen_fields(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        ActorDetail.model_validate(
            {
                "actor_id": str(uid),
                "primary_handle": "@x",
                "alias_count": 0,
                "observation_count": 0,
            },
        )


# --- NeighborEdge discriminated union --------------------------------------


def test_neighbor_edge_dispatches_linked_to(uid: UUID, uid2: UUID) -> None:
    adapter: TypeAdapter[NeighborEdge] = TypeAdapter(NeighborEdge)
    parsed = adapter.validate_python(
        {
            "edge_type": "linked_to",
            "target_id": str(uid2),
            "attrs": {
                "state": LinkageState.CONFIRMED,
                "method": "stylometry",
                "score": 0.91,
                "linkage_id": str(uid),
            },
        },
    )
    assert isinstance(parsed, LinkedToEdge)
    assert parsed.attrs.method == "stylometry"


def test_neighbor_edge_dispatches_belongs_to_persona(uid: UUID, uid2: UUID, now: datetime) -> None:
    adapter: TypeAdapter[NeighborEdge] = TypeAdapter(NeighborEdge)
    parsed = adapter.validate_python(
        {
            "edge_type": "belongs_to_persona",
            "target_id": str(uid),
            "attrs": {"since": now.isoformat(), "via_linkage_id": str(uid2)},
        },
    )
    assert isinstance(parsed, BelongsToPersonaEdge)
    assert parsed.attrs.via_linkage_id == uid2


def test_neighbor_edge_rejects_unknown_discriminator(uid: UUID) -> None:
    adapter: TypeAdapter[NeighborEdge] = TypeAdapter(NeighborEdge)
    with pytest.raises(PydanticValidationError) as exc_info:
        adapter.validate_python(
            {"edge_type": "frenemies", "target_id": str(uid), "attrs": {}},
        )
    # Pydantic's discriminator error message names the bad value.
    assert "frenemies" in str(exc_info.value) or "discriminator" in str(exc_info.value).lower()


def test_linked_to_attrs_requires_all_fields(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        LinkedToAttrs.model_validate({"state": LinkageState.PROPOSED, "method": "m", "score": 0.5})


def test_belongs_to_persona_attrs_optional_via_linkage(now: datetime) -> None:
    attrs = BelongsToPersonaAttrs(since=now)
    assert attrs.via_linkage_id is None


def test_neighbor_list_typed_items(uid: UUID, uid2: UUID) -> None:
    nl = NeighborList(
        items=[
            LinkedToEdge(
                target_id=uid2,
                attrs=LinkedToAttrs(
                    state=LinkageState.CONFIRMED,
                    method="m",
                    score=0.9,
                    linkage_id=uid,
                ),
            ),
        ],
    )
    assert len(nl.items) == 1


# --- ObservationSummary / TimelineEntry -------------------------------------


def test_observation_summary_minimal(uid: UUID, now: datetime) -> None:
    obs = ObservationSummary(
        observation_id=uid,
        kind="stylometry:trigram",
        ts=now,
        sensitivity=SensitivityTier.NORMAL,
    )
    assert obs.score is None
    assert obs.primitive is None
    assert obs.attachment_blob_id is None


def test_observation_summary_requires_sensitivity(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        ObservationSummary.model_validate(
            {"observation_id": str(uid), "kind": "k", "ts": now.isoformat()},
        )


@pytest.mark.parametrize("tier", list(SensitivityTier))
def test_observation_summary_every_tier(uid: UUID, now: datetime, tier: SensitivityTier) -> None:
    obs = ObservationSummary(observation_id=uid, kind="k", ts=now, sensitivity=tier)
    assert obs.sensitivity is tier


@pytest.mark.parametrize("kind", ["message", "observation"])
def test_timeline_entry_kind_literal(uid: UUID, now: datetime, kind: str) -> None:
    entry = TimelineEntry(ts=now, kind=kind, id=uid)  # type: ignore[arg-type]
    assert entry.kind == kind


def test_timeline_entry_rejects_other_kind(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        TimelineEntry.model_validate(
            {"ts": now.isoformat(), "kind": "raw_event", "id": str(uid)},
        )
