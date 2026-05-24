"""Best-effort resolver: (source, group, platform_msgid) -> MessageTable.id.

Replies, edits, and reactions all reference a target message by its
**platform** id (Matrix event_id, Telegram msg_id). The MessageTable FK
is a EYENET-internal UUID. This helper bridges the two at insert time.

Out-of-order arrivals (live event references a still-unsynced backfilled
ancestor) are common in practice. M8 takes the cheap path: do the lookup
once at insert, and if it misses, leave the FK None and stash the platform
id under `source_specific.pending_reply_to` for a future M9 backfill
resolver to recover. See [[feedback_small_operator_scope]] — we defer the
background resolver until an operator actually asks for it.
"""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from eyenet.models import MessageTable


def resolve_message_id(
    session: Session,
    *,
    source_id: UUID,
    group_id: UUID,
    platform_msgid: str,
) -> UUID | None:
    """Return the MessageTable.id for `platform_msgid` in this group, if known.

    Cheap: one indexed lookup on `(source_id, group_id, platform_msgid)`.
    Returns None when the target message has not been ingested yet — the
    caller decides whether to drop, stash, or defer.
    """

    row = session.exec(
        select(MessageTable.id).where(
            MessageTable.source_id == source_id,
            MessageTable.group_id == group_id,
            MessageTable.platform_msgid == platform_msgid,
        )
    ).first()
    if row is None:
        return None
    return UUID(str(row))


__all__ = ["resolve_message_id"]
