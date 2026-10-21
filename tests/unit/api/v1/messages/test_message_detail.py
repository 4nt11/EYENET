# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the by-id message/thread detail handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser, ResourceNotFound
from eyenet.api.v1.messages.api_get_message import messages_get
from eyenet.api.v1.threads.api_get_thread import threads_get
from eyenet.contracts.enums import SystemUserRole
from eyenet.models import InfrastructureArtifactMentionTable, InfrastructureArtifactTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from tests._seed import seed_telegram_fixture

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({"read:observations"}),
        token_expires_at=None,
    )


async def _seed_two_posts(storage: BaseRepository):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    records = [
        {
            "actor_key": "a",
            "platform_msgid": "1",
            "body": "first post, the OP",
            "sent_at_source": now.isoformat(),
        },
        {
            "actor_key": "b",
            "platform_msgid": "2",
            "body": "a reply",
            "sent_at_source": (now + timedelta(minutes=5)).isoformat(),
        },
    ]
    source_id, group_id, _ = await seed_telegram_fixture(storage, records, now)
    posts = await storage.messages_for_group(group_id, limit=10)  # oldest-first
    return source_id, group_id, posts, now


async def _attach_artifact(storage: BaseRepository, message_id, now) -> None:
    art = InfrastructureArtifactTable(
        kind="btc_wallet",
        value="bc1qexample",
        value_hash="h",
        first_seen_at_ingest=now,
        last_seen_at_ingest=now,
    )
    async with storage.session() as session:
        session.add(art)
        await session.flush()
        session.add(
            InfrastructureArtifactMentionTable(artifact_id=art.id, message_id=message_id, ts=now)
        )
        await session.commit()


async def test_message_detail_happy_path(storage: BaseRepository) -> None:
    _, group_id, posts, now = await _seed_two_posts(storage)
    op = posts[0]
    await _attach_artifact(storage, op.id, now)

    detail = await messages_get(op.id, _user(), storage)

    assert detail.message.id == op.id
    assert detail.message.body == "first post, the OP"
    assert detail.group_id == group_id
    assert detail.source_display == "telegram:tg_alpha"
    assert [a.value for a in detail.artifacts] == ["bc1qexample"]
    # a post with no artifact mentions comes back with an empty list, not an error
    plain = await messages_get(posts[1].id, _user(), storage)
    assert plain.artifacts == []


async def test_message_detail_404(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await messages_get(uuid4(), _user(), storage)


async def test_thread_detail_op_and_count(storage: BaseRepository) -> None:
    _, group_id, posts, now = await _seed_two_posts(storage)
    await _attach_artifact(storage, posts[0].id, now)

    thread = await threads_get(group_id, _user(), storage)

    assert thread.thread_id == group_id
    assert thread.post_count == 2
    assert thread.op.message.id == posts[0].id  # OP is the earliest post
    assert thread.op.message.body == "first post, the OP"
    assert [a.value for a in thread.op.artifacts] == ["bc1qexample"]


async def test_thread_detail_404_unknown_group(storage: BaseRepository) -> None:
    with pytest.raises(ResourceNotFound):
        await threads_get(uuid4(), _user(), storage)
