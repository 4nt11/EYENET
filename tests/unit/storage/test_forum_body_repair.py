# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum body repair: recover full URLs from retained body_html, rewrite body."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.collectors.forum._mybb import body_text_from_html
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_FULL = "nanrwa6b4z7vo5hxi64faaidcomwylxlb6bhtwcoh6dkagp3ykhm3uqd.onion"


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _forum_msg(storage: BaseRepository, *, mangled_body: str, body_html: str) -> None:
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    src = await storage.upsert_source(kind=SourceKind.FORUM, display_name="f", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src, platform_groupid="c", kind=GroupKind.FORUM_CATEGORY, title="c", seen_at=_NOW
    )
    actor, _ = await storage.upsert_actor(
        source_id=src, actor_key="a", platform_userid="1", handle="h", display_name="d", seen_at=_NOW
    )
    await storage.put_message(
        MessageTable(
            id=new_uuid7(),
            source_id=src,
            group_id=gid,
            actor_id=actor,
            platform_msgid="m1",
            evidence_ref="mybb:1",
            body=mangled_body,
            length_chars=len(mangled_body),
            length_words=len(mangled_body.split()),
            sent_at_source=_NOW,
            ingested_at=_NOW,
            source_specific={"body_html": body_html},
        ),
        None,
    )


async def test_repair_recovers_full_onion(storage: BaseRepository) -> None:
    html = f'<a class="mycode_url" href="http://{_FULL}/">http://nanrwa...uqd.onion/</a>'
    await _forum_msg(storage, mangled_body="http://nanrwa...uqd.onion/", body_html=html)

    cands = await storage.forum_messages_for_body_repair(limit=50)
    assert len(cands) == 1
    mid, body, got_html = cands[0]
    assert "..." in body  # stored body is still the mangled display

    fixed = body_text_from_html(got_html)
    n = await storage.update_message_bodies_bulk([(mid, fixed, len(fixed), len(fixed.split()))])
    assert n == 1

    # Re-read: body now carries the full onion, no ellipsis.
    after = await storage.forum_messages_for_body_repair(limit=50)
    assert _FULL in after[0][1]
    assert "..." not in after[0][1]


async def test_repair_ignores_non_forum_and_plain_messages(storage: BaseRepository) -> None:
    # A body_html without an auto-link is not a repair candidate.
    await _forum_msg(storage, mangled_body="just text", body_html="<p>just text</p>")
    assert await storage.forum_messages_for_body_repair(limit=50) == []
