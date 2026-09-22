# SPDX-License-Identifier: AGPL-3.0-or-later
"""list_observations_for_case / count_observations_for_case (ObservationsMixin).

Direct-membership semantics (§4.10.1): only observations added to the case via
``case_member`` (subject_kind=observation, not removed) are returned. Types
against BaseRepository + get_repository per Rule 2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.enums import CaseSubjectKind, ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.models.observation import ObservationTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
_USER = UUID("00000000-0000-0000-0000-0000000000ff")
_CTX = {"service": "test", "instance_id": "t0"}


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _obs(*, observed_at: datetime = _NOW, actor_id: UUID | None = None) -> ObservationRow:
    return ObservationRow(
        id=_new_uuid7(),
        actor_id=actor_id or uuid4(),
        primitive_namespace="lexical",
        primitive_name="lexical.vocabulary_richness",
        primitive_version="0.1",
        value_kind=ValueKind.NUMERIC,
        value_numeric=0.5,
        evidence_ref="test:ref",
        observed_at=observed_at,
        sensor_instance="test",
    )


async def _new_case(storage: BaseRepository) -> UUID:
    case = await storage.create_case(
        title="evidence case", description=None, opened_by_user_id=_USER, **_CTX
    )
    return case.id


async def _add_obs_member(storage: BaseRepository, case_id: UUID, obs_id: UUID) -> UUID:
    member = await storage.add_case_member(
        case_id=case_id,
        subject_kind=CaseSubjectKind.OBSERVATION,
        subject_id=obs_id,
        added_by_user_id=_USER,
        reason="seed evidence member",
        **_CTX,
    )
    return member.id


async def test_empty_case_has_no_observations(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    assert await storage.list_observations_for_case(case_id, limit=10) == []
    assert await storage.count_observations_for_case(case_id) == 0


async def test_only_direct_members_returned(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    member = _obs()
    non_member = _obs()
    await storage.put_observation(member)
    await storage.put_observation(non_member)
    await _add_obs_member(storage, case_id, member.id)

    rows = await storage.list_observations_for_case(case_id, limit=10)
    assert [r.id for r in rows] == [member.id]  # type: ignore[attr-defined]
    assert all(isinstance(r, ObservationTable) for r in rows)
    assert await storage.count_observations_for_case(case_id) == 1


async def test_newest_first(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    older = _obs(observed_at=_NOW)
    newer = _obs(observed_at=_NOW + timedelta(hours=1))
    for o in (older, newer):
        await storage.put_observation(o)
        await _add_obs_member(storage, case_id, o.id)
    rows = await storage.list_observations_for_case(case_id, limit=10)
    assert [r.id for r in rows] == [newer.id, older.id]  # type: ignore[attr-defined]


async def test_removed_member_excluded(storage: BaseRepository) -> None:
    case_id = await _new_case(storage)
    obs = _obs()
    await storage.put_observation(obs)
    member_id = await _add_obs_member(storage, case_id, obs.id)

    await storage.remove_case_member(
        member_id=member_id, remover_user_id=_USER, reason="no longer evidence", **_CTX
    )
    assert await storage.list_observations_for_case(case_id, limit=10) == []
    assert await storage.count_observations_for_case(case_id) == 0


async def test_scoped_to_case(storage: BaseRepository) -> None:
    case_a = await _new_case(storage)
    case_b = await _new_case(storage)
    obs = _obs()
    await storage.put_observation(obs)
    await _add_obs_member(storage, case_a, obs.id)
    assert await storage.count_observations_for_case(case_a) == 1
    assert await storage.count_observations_for_case(case_b) == 0
