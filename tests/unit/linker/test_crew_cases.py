# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crew -> Case: idempotent promotion + auto-open sweep."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.enums import CaseSubjectKind, SourceKind
from eyenet.linker.crew_cases import (
    crew_key_for,
    open_case_for_crew,
    open_cases_for_big_crews,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


@pytest.mark.unit
def test_crew_key_dominant_indicator() -> None:
    assert crew_key_for(["handle:wbpay", "handle:lv"], [uuid4()]) == "handle:wbpay"


@pytest.mark.unit
def test_crew_key_empty_infra_is_member_hash_order_independent() -> None:
    m = [UUID(int=1), UUID(int=2), UUID(int=3)]
    k = crew_key_for([], m)
    assert k.startswith("crew:")
    assert k == crew_key_for([], list(reversed(m)))


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _actors(storage: BaseRepository, src: UUID, n: int) -> list[UUID]:
    now = datetime.now(tz=UTC)
    out = []
    for i in range(n):
        out.append(
            await storage.upsert_actor(
                source_id=src,
                actor_key=f"actor:{i}",
                platform_userid=str(i),
                handle=None,
                display_name=f"bot{i}",
                seen_at=now,
            )
        )
    return out


@pytest.mark.unit
async def test_open_case_for_crew_idempotent(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    members = await _actors(storage, src, 3)
    user = uuid4()
    c1 = await open_case_for_crew(
        storage,
        members=members,
        top_infra=["handle:wbpay"],
        opened_by_user_id=user,
        service="t",
        instance_id="t",
    )
    c2 = await open_case_for_crew(
        storage,
        members=members,
        top_infra=["handle:wbpay"],
        opened_by_user_id=user,
        service="t",
        instance_id="t",
    )
    assert c1.id == c2.id  # idempotent on crew_key
    assert await storage.get_case_by_crew_key("handle:wbpay") is not None
    member_rows = await storage.list_case_members(case_id=c1.id)
    actor_members = [m for m in member_rows if m.subject_kind is CaseSubjectKind.ACTOR]
    assert {m.subject_id for m in actor_members} == set(members)


@pytest.mark.unit
async def test_auto_sweep_opens_only_big_high_score(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    big = await _actors(storage, src, 8)
    small = await _actors(storage, src, 2)

    # Big crew: star of 7 edges around big[0], all high score + shared handle.
    for other in big[1:]:
        await storage.insert_proposed_linkage(
            actor_a=big[0],
            actor_b=other,
            method="shared_infra",
            score=0.9,
            evidence={"shared": ["handle:xldf_bot"]},
        )
    # Small crew: below the size threshold.
    await storage.insert_proposed_linkage(
        actor_a=small[0],
        actor_b=small[1],
        method="shared_infra",
        score=0.95,
        evidence={"shared": ["handle:tiny"]},
    )

    opened = await open_cases_for_big_crews(
        storage,
        opened_by_user_id=uuid4(),
        service="cli",
        instance_id="crew-cases",
        min_size=8,
        min_score=0.8,
    )
    assert opened == 1
    # Re-run is idempotent.
    assert (
        await open_cases_for_big_crews(
            storage,
            opened_by_user_id=uuid4(),
            service="cli",
            instance_id="crew-cases",
            min_size=8,
            min_score=0.8,
        )
        == 0
    )
    assert await storage.get_case_by_crew_key("handle:xldf_bot") is not None
    assert await storage.get_case_by_crew_key("handle:tiny") is None  # too small
