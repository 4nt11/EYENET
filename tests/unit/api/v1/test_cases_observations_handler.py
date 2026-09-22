# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for GET /v1/cases/{case_id}/observations.

Direct-membership + case-visibility semantics. Bypasses ASGI routing (coverage
can't trace it) and the RequireScope dependency; visibility is enforced inside
the handler via require_case_visible, which we exercise here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.cases.api_list_case_observations import cases_list_observations
from eyenet.contracts._base import _new_uuid7
from eyenet.contracts.enums import CaseSubjectKind, ValueKind
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
_USER = UUID("00000000-0000-0000-0000-0000000000ff")
_CTX = {"service": "test", "instance_id": "t0"}
_PAGE = CursorParams(offset=0, limit=50, include_total=True)


def _obs() -> ObservationRow:
    return ObservationRow(
        id=_new_uuid7(),
        actor_id=uuid4(),
        primitive_namespace="lexical",
        primitive_name="lexical.vocabulary_richness",
        primitive_version="0.1",
        value_kind=ValueKind.NUMERIC,
        value_numeric=0.5,
        evidence_ref="test:ref",
        observed_at=_NOW,
        sensor_instance="test",
    )


async def _case_with_obs(storage: BaseRepository) -> tuple[UUID, UUID]:
    case = await storage.create_case(
        title="evidence case", description=None, opened_by_user_id=_USER, **_CTX
    )
    obs = _obs()
    await storage.put_observation(obs)
    await storage.add_case_member(
        case_id=case.id,
        subject_kind=CaseSubjectKind.OBSERVATION,
        subject_id=obs.id,
        added_by_user_id=_USER,
        reason="seed evidence member",
        **_CTX,
    )
    return case.id, obs.id


async def test_lists_case_member_observations(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    case_id, obs_id = await _case_with_obs(storage)
    # admin:case satisfies require_case_visible without a collaborator row.
    res = await cases_list_observations(case_id, mkuser("admin:case"), storage, _PAGE)
    assert [i.observation_id for i in res.items] == [obs_id]
    assert res.estimated_total == 1


async def test_missing_case_raises_not_found(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await cases_list_observations(uuid4(), mkuser("admin:case"), storage, _PAGE)


async def test_non_visible_case_raises_not_found(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    # A caller who is neither admin:case nor a collaborator must not be able to
    # tell an existing-but-invisible case from an absent one (no oracle).
    case_id, _ = await _case_with_obs(storage)
    with pytest.raises(ResourceNotFound):
        await cases_list_observations(case_id, mkuser(), storage, _PAGE)
