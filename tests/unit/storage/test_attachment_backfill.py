# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attachment backfill repo surface: iter_attachment_shells + the blob/link setters.

A shell = source_ref IS NULL (the "not processed by the download path" marker). Once
backfill stores the blob OR records the link, the row drops out of the shell set."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import AttachmentKind, GroupKind, SourceKind
from eyenet.models import AttachmentTable, MessageTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _seed_shell(storage: BaseRepository) -> tuple[object, str, str]:
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src,
        platform_groupid="-1001234567890",
        kind=GroupKind.CHANNEL,
        title="g",
        seen_at=_NOW,
    )
    actor, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="k",
        platform_userid="u",
        handle="h",
        display_name="h",
        seen_at=_NOW,
    )
    msg = MessageTable(
        source_id=src,
        group_id=gid,
        actor_id=actor,
        platform_msgid="777",
        evidence_ref="telegram:-1001234567890:777",
        body="x",
        length_chars=1,
        length_words=1,
        sent_at_source=_NOW,
        ingested_at=_NOW,
        has_attachment=True,
    )
    att = AttachmentTable(
        message_id=msg.id,
        kind=AttachmentKind.IMAGE,
        mime="image/jpeg",
        size_bytes=0,
        sha256="0" * 64,
        filename=None,
        storage_uri=None,
        source_ref=None,
    )
    await storage.put_message(msg, [att])
    return src, att.id, "-1001234567890"


async def test_shell_listed_then_blob_fill_removes_it(storage: BaseRepository) -> None:
    src, att_id, groupid = await _seed_shell(storage)
    shells = await storage.iter_attachment_shells(src, limit=10)
    assert shells == [(att_id, groupid, "777")]

    await storage.set_attachment_blob(
        att_id,
        sha256="a" * 64,
        size_bytes=1234,
        storage_uri="/data/x.bin",
        source_ref="https://t.me/c/1234567890/777",
    )
    assert await storage.iter_attachment_shells(src, limit=10) == []
    got = await storage.get_attachment(att_id)
    assert got is not None and got.storage_uri == "/data/x.bin" and got.size_bytes == 1234
    await storage.close()


async def test_link_only_also_removes_it(storage: BaseRepository) -> None:
    src, att_id, _ = await _seed_shell(storage)
    await storage.set_attachment_source_ref(att_id, "https://t.me/c/1234567890/777")
    assert await storage.iter_attachment_shells(src, limit=10) == []
    got = await storage.get_attachment(att_id)
    # link recorded, but no blob stored (still over the gate)
    assert got is not None and got.storage_uri is None
    await storage.close()
