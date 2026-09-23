# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the §5.9 audit-anchor read handler."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.audit.api_list_anchors import audit_list_anchors
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_SIG = "ed25519:" + ("A" * 86) + "=="


async def _seed(storage: BaseRepository, *, deployment, seq: int, at: datetime) -> None:
    await storage.record_anchor(
        deployment_id=deployment,
        anchor_seq=seq,
        anchored_at=at,
        audit_head="0" * 64,
        journal_head="0" * 64,
        signature=_SIG,
    )


async def test_list_newest_first_and_paginates(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    deployment = uuid4()
    base = datetime.now(tz=UTC)
    for i in range(3):
        await _seed(storage, deployment=deployment, seq=i, at=base + timedelta(minutes=i))

    first = await audit_list_anchors(mkuser("read:audit"), storage, None, 2, None, None)
    assert len(first.items) == 2
    assert first.items[0].anchor_seq == 2  # newest first
    assert first.next_cursor is not None

    second = await audit_list_anchors(
        mkuser("read:audit"), storage, first.next_cursor, 2, None, None
    )
    assert len(second.items) == 1
    assert second.next_cursor is None


async def test_list_empty(storage: BaseRepository, mkuser: Callable[..., CurrentUser]) -> None:
    page = await audit_list_anchors(mkuser("read:audit"), storage, None, 50, None, None)
    assert page.items == []
    assert page.next_cursor is None
