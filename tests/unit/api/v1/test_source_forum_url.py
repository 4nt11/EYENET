# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum base URL surfaced on the source read surface.

Two forums reuse the same category slugs (both MyBB -> both have "Forum-Databases"),
so the groups/candidates views disambiguate by the source's forum base URL. It
lives on the collecting identity's source_config; the source read surface resolves
it (None for non-forum sources).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.api.v1.sources._detail import build_source_detail, resolve_forum_base_url
from eyenet.contracts.enums import SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_forum_base_url_from_identity(storage: BaseRepository) -> None:
    src = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="forum:pwn", created_at=_NOW
    )
    await storage.create_identity(
        name="pwn",
        source_id=src,
        session_path="/tmp/pwn",  # noqa: S108 — test stub
        source_config={"forum_base_url": "http://host.onion", "forum_evasion_level": "ghost"},
    )
    row = await storage.get_source(src)
    assert await resolve_forum_base_url(storage, row) == "http://host.onion"

    detail = await build_source_detail(storage, src)
    assert detail is not None and detail.forum_base_url == "http://host.onion"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_forum_base_url_none_for_non_forum(storage: BaseRepository) -> None:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    row = await storage.get_source(src)
    assert await resolve_forum_base_url(storage, row) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_forum_base_url_none_when_identity_lacks_it(storage: BaseRepository) -> None:
    # A forum source whose identity carries no base URL yet -> None, not a crash.
    src = await storage.upsert_source(
        kind=SourceKind.FORUM, display_name="forum:bare", created_at=_NOW
    )
    await storage.create_identity(
        name="bare",
        source_id=src,
        session_path="/tmp/bare",  # noqa: S108
    )
    row = await storage.get_source(src)
    assert await resolve_forum_base_url(storage, row) is None
