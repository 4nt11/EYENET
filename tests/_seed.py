"""Async test seed helpers for the flat repository.

Shared utility for integration/e2e tests that need to populate the
storage with a synthetic source/group/actor/message graph from a
fixture-like dict. Replaces the old pattern of opening a raw Session
and calling sync `upsert_*` free functions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.repository import BaseRepository


async def seed_telegram_fixture(
    storage: BaseRepository,
    records: list[dict[str, Any]],
    now: datetime,
    *,
    source_display_name: str = "telegram:tg_alpha",
    platform_groupid: str = "-100",
    group_title: str = "Test",
) -> tuple[Any, Any, dict[str, Any]]:
    """Seed source + group + per-actor rows + messages, return ids.

    Returns ``(source_id, group_id, actor_ids)``. Sets ``reply_to_msg_id``
    in a second pass for records that carry ``reply_to_platform_msgid``.
    """
    source_id = await storage.upsert_source(
        kind=SourceKind.TELEGRAM,
        display_name=source_display_name,
        created_at=now,
    )
    group_id = await storage.upsert_group(
        source_id=source_id,
        platform_groupid=platform_groupid,
        kind=GroupKind.CHAT,
        title=group_title,
        seen_at=now,
    )
    actor_ids: dict[str, Any] = {}
    for rec in records:
        ak = rec["actor_key"]
        if ak not in actor_ids:
            actor_ids[ak] = await storage.upsert_actor(
                source_id=source_id,
                actor_key=ak,
                platform_userid=ak[-8:],
                handle=None,
                display_name=None,
                seen_at=now,
            )

    platform_to_uuid: dict[str, Any] = {}
    for rec in records:
        body = rec.get("body", "")
        msgid = rec["platform_msgid"]
        ref = f"telegram:{platform_groupid}:{msgid}"
        sent_raw = rec.get("sent_at_source")
        sent = datetime.fromisoformat(sent_raw) if sent_raw else now
        row = MessageTable(
            id=new_uuid7(),
            source_id=source_id,
            group_id=group_id,
            actor_id=actor_ids[rec["actor_key"]],
            platform_msgid=msgid,
            evidence_ref=ref,
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=sent,
            ingested_at=now,
        )
        await storage.put_message(row)
        platform_to_uuid[msgid] = row.id

    async with storage.session() as session:
        from sqlmodel import select

        for rec in records:
            rkey = rec.get("reply_to_platform_msgid")
            if rkey and rkey in platform_to_uuid:
                ref = f"telegram:{platform_groupid}:{rec['platform_msgid']}"
                result = await session.exec(
                    select(MessageTable).where(MessageTable.evidence_ref == ref)
                )
                msg = result.first()
                if msg is not None:
                    msg.reply_to_msg_id = platform_to_uuid[rkey]
                    session.add(msg)
        await session.commit()

    return source_id, group_id, actor_ids


__all__ = ["seed_telegram_fixture"]
