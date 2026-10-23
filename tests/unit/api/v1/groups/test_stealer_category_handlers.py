# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the stealer-category handlers (mark + list)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.groups.api_list_stealer_channels import stealer_channels_list
from eyenet.api.v1.groups.api_mark_group_category import groups_mark_category
from eyenet.api.v1.schemas.groups import SetGroupCategoryRequest
from eyenet.bus.memory import MemoryBus
from eyenet.contracts.bus import Bus
from eyenet.contracts.enums import GroupKind, SystemUserRole
from eyenet.contracts.group import (
    GROUP_CATEGORY_CHANGED_SUBJECT,
    STEALER_LOG_CATEGORY as STEALER_CATEGORY,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def bus() -> Bus:
    return MemoryBus()


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"admin:stealer", "read:stealer"}),
        token_expires_at=None,
    )


async def test_mark_sets_and_clears_category(storage: BaseRepository, bus: Bus) -> None:
    gid = await storage.create_operator_group(title="chan", kind=GroupKind.CHANNEL, now=_NOW)

    detail = await groups_mark_category(
        gid, SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage, bus
    )
    assert detail.group_id == gid
    assert detail.category == STEALER_CATEGORY

    cleared = await groups_mark_category(
        gid, SetGroupCategoryRequest(category=None), _user(), storage, bus
    )
    assert cleared.category is None
    await storage.close()


async def test_mark_publishes_category_changed(storage: BaseRepository) -> None:
    """A successful mark broadcasts so collectors refresh their stealer set."""
    seen: list[str] = []

    async def _handler(subject: str, _payload: bytes, _headers: dict[str, str]) -> None:
        seen.append(subject)

    bus = MemoryBus()
    await bus.subscribe(GROUP_CATEGORY_CHANGED_SUBJECT, _handler)
    gid = await storage.create_operator_group(title="chan", kind=GroupKind.CHANNEL, now=_NOW)
    await groups_mark_category(
        gid, SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage, bus
    )
    assert seen == [GROUP_CATEGORY_CHANGED_SUBJECT]
    await storage.close()


async def test_mark_unknown_group_raises(storage: BaseRepository, bus: Bus) -> None:
    with pytest.raises(ResourceNotFound):
        await groups_mark_category(
            uuid4(), SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage, bus
        )
    await storage.close()


async def test_list_returns_only_marked_channels(storage: BaseRepository, bus: Bus) -> None:
    marked = await storage.create_operator_group(title="a", kind=GroupKind.CHANNEL, now=_NOW)
    await storage.create_operator_group(title="b", kind=GroupKind.CHANNEL, now=_NOW)  # unmarked
    await groups_mark_category(
        marked, SetGroupCategoryRequest(category=STEALER_CATEGORY), _user(), storage, bus
    )

    rows = await stealer_channels_list(_user(), storage, source_id=None)
    assert [r.group_id for r in rows] == [marked]
    assert rows[0].category == STEALER_CATEGORY

    # bogus source scopes to empty
    assert await stealer_channels_list(_user(), storage, source_id=uuid4()) == []
    await storage.close()
