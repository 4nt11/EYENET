# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the stealer-category handlers (mark + list)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.groups.api_list_stealer_channels import (
    STEALER_CATEGORY,
    stealer_channels_list,
)
from eyenet.api.v1.groups.api_mark_group_category import groups_mark_category
from eyenet.api.v1.schemas.groups import SetGroupCategoryRequest
from eyenet.contracts.enums import GroupKind, SystemUserRole
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"admin:stealer", "read:stealer"}),
        token_expires_at=None,
    )


async def test_mark_sets_and_clears_category(storage: BaseRepository) -> None:
    gid = await storage.create_operator_group(title="chan", kind=GroupKind.CHANNEL, now=_NOW)

    detail = await groups_mark_category(
        gid, SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage
    )
    assert detail.group_id == gid
    assert detail.category == STEALER_CATEGORY

    cleared = await groups_mark_category(
        gid, SetGroupCategoryRequest(category=None), _user(), storage
    )
    assert cleared.category is None
    await storage.close()


async def test_mark_unknown_group_raises(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await groups_mark_category(
            uuid4(), SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage
        )
    await storage.close()


async def test_list_returns_only_marked_channels(storage: BaseRepository) -> None:
    marked = await storage.create_operator_group(title="a", kind=GroupKind.CHANNEL, now=_NOW)
    await storage.create_operator_group(title="b", kind=GroupKind.CHANNEL, now=_NOW)  # unmarked
    await groups_mark_category(
        marked, SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage
    )

    rows = await stealer_channels_list(_user(), storage, source_id=None)
    assert [r.group_id for r in rows] == [marked]
    assert rows[0].category == STEALER_CATEGORY

    # bogus source scopes to empty
    assert await stealer_channels_list(_user(), storage, source_id=uuid4()) == []
    await storage.close()
