# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit test for the generic visible-group scan seam (no live client)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.collectors.base.skeleton import CollectorSkeleton, VisibleGroup
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository


class _StubPool:
    async def claim(self, name: str) -> object:
        raise NotImplementedError

    async def release(self, name: str, *, new_state: object) -> None: ...
    async def freeze_all(self) -> None: ...


class _ScanCollector(CollectorSkeleton):
    """Overrides just the per-source enumeration seam."""

    async def enumerate_visible_groups(self) -> list[VisibleGroup]:
        return [
            VisibleGroup(platform_groupid="@x", kind=GroupKind.CHANNEL, title="X", is_member=True),
            VisibleGroup(platform_groupid="@y", kind=GroupKind.CHAT, title="Y", is_member=True),
        ]


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
async def test_scan_upserts_member_dialog_candidates(storage: BaseRepository) -> None:
    sid = await storage.upsert_source(
        kind=SourceKind.TELEGRAM, display_name="tg", created_at=datetime.now(tz=UTC)
    )
    collector = _ScanCollector(
        bus=MemoryBus(),
        storage=storage,
        pool=_StubPool(),
        identity_name="i",
        source_kind=SourceKind.TELEGRAM,
    )

    count = await collector.scan_visible_groups(source_id=sid)
    assert count == 2

    rows = await storage.list_candidates(limit=50)
    by_gid = {r.platform_groupid: r for r in rows}
    assert set(by_gid) == {"@x", "@y"}
    assert all(r.member_dialog for r in rows)
    assert by_gid["@x"].kind_hint is GroupKind.CHANNEL


@pytest.mark.unit
async def test_base_enumeration_not_implemented(storage: BaseRepository) -> None:
    base = CollectorSkeleton(
        bus=MemoryBus(),
        storage=storage,
        pool=_StubPool(),
        identity_name="i",
        source_kind=SourceKind.MATRIX,
    )
    with pytest.raises(NotImplementedError):
        await base.enumerate_visible_groups()
