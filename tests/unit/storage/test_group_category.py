# SPDX-License-Identifier: AGPL-3.0-or-later
"""Group collection-class ``category`` mixin: set/clear + list by category.

Types against BaseRepository + constructs via get_repository (Rule 2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.enums import GroupKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_set_group_category_marks_and_clears(storage: BaseRepository) -> None:
    gid = await storage.create_operator_group(title="logs chan", kind=GroupKind.CHANNEL, now=_NOW)
    g = await storage.get_group(gid)
    assert g is not None and g.category is None  # default

    assert await storage.set_group_category(gid, "stealer_logs") is True
    g = await storage.get_group(gid)
    assert g is not None and g.category == "stealer_logs"

    assert await storage.set_group_category(gid, None) is True  # clear
    g = await storage.get_group(gid)
    assert g is not None and g.category is None
    await storage.close()


async def test_set_group_category_unknown_group_returns_false(storage: BaseRepository) -> None:
    assert await storage.set_group_category(uuid4(), "stealer_logs") is False
    await storage.close()


async def test_list_groups_by_category_filters_and_scopes(storage: BaseRepository) -> None:
    marked = await storage.create_operator_group(title="a", kind=GroupKind.CHANNEL, now=_NOW)
    await storage.create_operator_group(title="b", kind=GroupKind.CHANNEL, now=_NOW)  # unmarked
    await storage.set_group_category(marked, "stealer_logs")

    rows = await storage.list_groups_by_category("stealer_logs")
    assert [r.id for r in rows] == [marked]  # only the marked one

    # source scoping: operator groups share the operator source
    op_src = await storage.get_or_create_operator_source(now=_NOW)
    scoped = await storage.list_groups_by_category("stealer_logs", source_id=op_src)
    assert [r.id for r in scoped] == [marked]
    assert await storage.list_groups_by_category("stealer_logs", source_id=uuid4()) == []
    await storage.close()
