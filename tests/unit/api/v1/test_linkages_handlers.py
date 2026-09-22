# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the M9.F2 linkage read handlers."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.deps_paging import CursorParams
from eyenet.api.v1.linkages.api_get_linkage import linkages_get
from eyenet.api.v1.linkages.api_list_linkages import linkages_list
from eyenet.contracts.enums import LinkageState, SystemUserRole
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


def _page() -> CursorParams:
    return CursorParams(offset=0, limit=50, include_total=True)


async def test_linkages_list_filters_and_counts(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    l1 = await storage.insert_proposed_linkage(uuid4(), uuid4(), "sty", 0.8, {})
    await storage.insert_proposed_linkage(uuid4(), uuid4(), "tmp", 0.6, {})
    page = await linkages_list(mkuser("read:linkages"), storage, _page(), None, "sty", None, None)
    assert page.estimated_total == 1
    assert {i.linkage_id for i in page.items} == {l1.id}


async def test_linkages_list_resolves_decided_by(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser], now
) -> None:
    decider = uuid4()
    await storage.put_system_user(
        user_id=decider,
        username="dec",
        display_name="Dec",
        role=SystemUserRole.ADMIN,
        created_at=now,
        is_active=True,
    )
    linkage = await storage.insert_proposed_linkage(uuid4(), uuid4(), "m", 0.5, {})
    await storage.transition_linkage(linkage.id, LinkageState.CONFIRMED, "dec")
    page = await linkages_list(
        mkuser("read:linkages"), storage, _page(), LinkageState.CONFIRMED, None, None, None
    )
    assert page.items[0].decided_by == decider


async def test_linkages_get_with_evidence(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    linkage = await storage.insert_proposed_linkage(
        uuid4(), uuid4(), "sty", 0.9, {"cosine": {"score": 0.9, "dim": 128}, "bad": "x"}
    )
    detail = await linkages_get(linkage.id, mkuser("read:linkages"), storage)
    comps = {e.comparator for e in detail.evidence}
    assert comps == {"cosine"}


async def test_linkages_get_surfaces_verifier(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    from datetime import UTC, datetime

    linkage = await storage.insert_proposed_linkage(uuid4(), uuid4(), "sty", 0.9, {})
    # No verifier result yet → None.
    detail = await linkages_get(linkage.id, mkuser("read:linkages"), storage)
    assert detail.verifier is None
    # After the Verifier scores it, the composite surfaces.
    await storage.record_verifier_result(
        linkage_id=linkage.id, composite=0.83, floor=0.6, state="suspected",
        results=[{"method": "general_impostors", "score": 0.86, "confidence": 1.0,
                  "skipped": False, "detail": "wins 43/50"}],
        computed_at=datetime.now(tz=UTC),
    )
    detail2 = await linkages_get(linkage.id, mkuser("read:linkages"), storage)
    assert detail2.verifier is not None
    assert detail2.verifier.composite == 0.83
    assert detail2.verifier.results[0].method == "general_impostors"


async def test_linkages_get_unknown_raises(
    storage: BaseRepository, mkuser: Callable[..., CurrentUser]
) -> None:
    with pytest.raises(ResourceNotFound):
        await linkages_get(uuid4(), mkuser("read:linkages"), storage)
