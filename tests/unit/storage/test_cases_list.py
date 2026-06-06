"""Storage tests for `list_cases` / `count_cases` (Slice A, API_PLAN §4.10).

Covers the index surface the `GET /v1/cases` handler needs: status filter,
`created_at DESC` ordering, the §4.10.4 collaborator list-visibility predicate,
and pagination offset/limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from eyenet.contracts.case import CaseRow
from eyenet.contracts.enums import CaseRoleOnCase, CaseStatus
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _case(
    storage: BaseRepository,
    *,
    title: str,
    at: datetime,
    opened_by: UUID | None = None,
) -> CaseRow:
    return await storage.create_case(
        title=title,
        description=None,
        opened_by_user_id=opened_by or uuid4(),
        now=at,
        service="t",
        instance_id="t1",
    )


@pytest.mark.unit
async def test_list_cases_orders_newest_first(storage: BaseRepository) -> None:
    a = await _case(storage, title="alpha", at=_NOW)
    b = await _case(storage, title="bravo", at=_NOW + timedelta(hours=1))
    c = await _case(storage, title="charlie", at=_NOW + timedelta(hours=2))

    rows = await storage.list_cases(limit=10)
    assert [r.id for r in rows] == [c.id, b.id, a.id]
    assert await storage.count_cases() == 3


@pytest.mark.unit
async def test_list_cases_status_filter(storage: BaseRepository) -> None:
    open_case = await _case(storage, title="still open", at=_NOW)
    closed = await _case(storage, title="to close", at=_NOW + timedelta(minutes=1))
    await storage.close_case(
        case_id=closed.id,
        closer_user_id=uuid4(),
        reason="closing this one for the test",
        now=_NOW + timedelta(minutes=2),
        service="t",
        instance_id="t1",
    )

    open_rows = await storage.list_cases(status=CaseStatus.OPEN, limit=10)
    assert [r.id for r in open_rows] == [open_case.id]
    assert await storage.count_cases(status=CaseStatus.OPEN) == 1
    assert await storage.count_cases(status=CaseStatus.CLOSED) == 1


@pytest.mark.unit
async def test_list_cases_collaborator_visibility(storage: BaseRepository) -> None:
    alice = uuid4()
    visible = await _case(storage, title="alice case", at=_NOW)
    await _case(storage, title="other case", at=_NOW + timedelta(minutes=1))
    await storage.add_case_collaborator(
        case_id=visible.id,
        user_id=alice,
        role=CaseRoleOnCase.OWNER,
        granted_by_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )

    rows = await storage.list_cases(collaborator_user_id=alice, limit=10)
    assert [r.id for r in rows] == [visible.id]
    assert await storage.count_cases(collaborator_user_id=alice) == 1
    # Unscoped listing still sees both.
    assert await storage.count_cases() == 2


@pytest.mark.unit
async def test_list_cases_revoked_collaborator_excluded(storage: BaseRepository) -> None:
    bob = uuid4()
    case = await _case(storage, title="bob case", at=_NOW)
    collab = await storage.add_case_collaborator(
        case_id=case.id,
        user_id=bob,
        role=CaseRoleOnCase.ANALYST,
        granted_by_user_id=uuid4(),
        now=_NOW,
        service="t",
        instance_id="t1",
    )
    await storage.revoke_case_collaborator(
        collaborator_id=collab.id,
        revoker_user_id=uuid4(),
        reason="no longer on this investigation",
        now=_NOW + timedelta(hours=1),
        service="t",
        instance_id="t1",
    )

    assert await storage.count_cases(collaborator_user_id=bob) == 0


@pytest.mark.unit
async def test_list_cases_pagination_offset_limit(storage: BaseRepository) -> None:
    made = [
        await _case(storage, title=f"case {i}", at=_NOW + timedelta(minutes=i)) for i in range(5)
    ]
    # newest-first: made[4], made[3], made[2], made[1], made[0]
    page1 = await storage.list_cases(limit=2, offset=0)
    page2 = await storage.list_cases(limit=2, offset=2)
    assert [r.id for r in page1] == [made[4].id, made[3].id]
    assert [r.id for r in page2] == [made[2].id, made[1].id]
    assert await storage.count_cases() == 5
