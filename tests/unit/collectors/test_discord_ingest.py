"""Unit tests for the Discord collector's pure ingest mappers (no storage/network)."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from eyenet.collectors.discord.real import (
    _actor_fields,
    _build_message_row,
    _emoji_str,
    _member_items,
    _parse_ts,
    _reaction_from_event,
    _resolve_rank,
)
from eyenet.contracts.enums import MembershipRole

pytestmark = pytest.mark.unit

# MortemTeam guild role table (real ids/perms from the gateway READY capture).
_MORTEM_ROLES = {
    "1559644444641202359": {"name": "Admin", "permissions": "8864258447638527"},
    "1561541094007771186": {"name": "MortemTeam", "permissions": "0"},
    "1560064810765393991": {"name": "Owner", "permissions": "1032"},
    "1560373184656572508": {"name": "SpicyMember", "permissions": "0"},
}


def _msg(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "1561528499259310182",
        "type": 0,
        "timestamp": "2026-10-18T22:32:17.123000+00:00",
        "edited_timestamp": None,
        "content": "Nroo",
        "author": {"id": "1335682327006679070", "username": "returnero",
                   "global_name": "mf$", "bot": False},
        "attachments": [],
        "embeds": [],
        "mentions": [],
    }
    base.update(over)
    return base


def test_parse_ts_utc() -> None:
    ts = _parse_ts("2026-10-18T22:32:17.123000+00:00")
    assert ts is not None and ts.tzinfo is not None
    assert ts.isoformat() == "2026-10-18T22:32:17.123000+00:00"


@pytest.mark.parametrize("bad", [None, "", "not-a-date"])
def test_parse_ts_bad_is_none_never_now(bad: str | None) -> None:
    # never now(): manufacturing recency on an old message is load-bearing-wrong.
    assert _parse_ts(bad) is None


def test_actor_fields_global_id_and_display() -> None:
    assert _actor_fields(
        {"id": "123", "username": "returnero", "global_name": "mf$", "bot": False}
    ) == ("123", "returnero", "mf$", False)


def test_actor_fields_bot_and_fallback_display() -> None:
    uid, handle, display, is_bot = _actor_fields({"id": "9", "username": "Security", "bot": True})
    assert (uid, handle, is_bot) == ("9", "Security", True)
    assert display == "Security"  # no global_name -> fall back to username


def test_build_row_evidence_ref_and_metadata() -> None:
    ts = _parse_ts(_msg()["timestamp"])
    assert ts is not None
    row = _build_message_row(
        source_id=uuid4(), group_id=uuid4(), actor_id=uuid4(),
        channel_id="1561241212504244395",
        msg=_msg(message_reference={"message_id": "999"},
                 reactions=[{"emoji": {"name": "🔥"}, "count": 2}]),
        sent_at=ts, now=ts,
    )
    assert row.evidence_ref == "discord:1561241212504244395:1561528499259310182"
    assert row.body == "Nroo"
    assert row.length_words == 1
    # responded_to + reactions survive for later resolution
    assert row.source_specific["message_reference"]["message_id"] == "999"
    assert row.source_specific["reactions"][0]["count"] == 2
    assert row.has_attachment is False


def test_build_row_attachments_and_embed_only() -> None:
    ts = _parse_ts(_msg()["timestamp"])
    assert ts is not None
    row = _build_message_row(
        source_id=uuid4(), group_id=uuid4(), actor_id=uuid4(), channel_id="c",
        msg=_msg(content="", embeds=[{"title": "leak", "description": "dump"}],
                 attachments=[{"id": "a1", "filename": "x.sql", "url": "http://h/x",
                               "size": 10, "content_type": "text/plain"}]),
        sent_at=ts, now=ts,
    )
    assert row.has_attachment is True
    assert row.source_specific["attachments"][0]["filename"] == "x.sql"
    assert row.source_specific["embeds"][0]["title"] == "leak"  # bot/drop payload kept
    assert row.body == ""  # embed-only message, empty content, still ingested


# ---- dispatch mappers (the diamond: reactions / member rank) -----------------

def test_resolve_rank_returnero_is_admin() -> None:
    # returnero's three roles: the Admin role carries the ADMINISTRATOR bit -> admin.
    rank, names = _resolve_rank(
        ["1559644444641202359", "1561541094007771186", "1560064810765393991"], _MORTEM_ROLES
    )
    assert rank is MembershipRole.ADMIN
    assert names == ["Admin", "MortemTeam", "Owner"]


def test_resolve_rank_tag_only_is_member() -> None:
    rank, names = _resolve_rank(["1561541094007771186"], _MORTEM_ROLES)
    assert rank is MembershipRole.MEMBER
    assert names == ["MortemTeam"]


def test_resolve_rank_unknown_role_ignored() -> None:
    rank, names = _resolve_rank(["does-not-exist", "1560373184656572508"], _MORTEM_ROLES)
    assert rank is MembershipRole.MEMBER
    assert names == ["SpicyMember"]  # unknown id dropped, known name kept


def test_emoji_str_unicode_vs_custom() -> None:
    assert _emoji_str({"name": "🔥", "id": None}) == "🔥"
    assert _emoji_str({"name": "pepe", "id": "999"}) == "pepe:999"


def test_reaction_from_event_ok_and_malformed() -> None:
    ok = _reaction_from_event(
        {"channel_id": "c", "message_id": "m", "user_id": "u", "emoji": {"name": "🔥"}}
    )
    assert ok == ("c", "m", "u", "🔥")
    assert _reaction_from_event({"channel_id": "c", "message_id": "m"}) is None  # no user/emoji


def test_member_items_single_update() -> None:
    d = {"guild_id": "g", "user": {"id": "42"}, "roles": ["r1"]}
    items = _member_items("GUILD_MEMBER_UPDATE", d)
    assert [m["user"]["id"] for m in items] == ["42"]


def test_member_items_list_update_skips_group_headers() -> None:
    d = {
        "guild_id": "g",
        "ops": [{"op": "SYNC", "range": [0, 1], "items": [
            {"group": {"id": "online", "count": 5}},  # section header, not a member
            {"member": {"user": {"id": "42"}, "roles": ["1559644444641202359"]}},
        ]}],
    }
    items = _member_items("GUILD_MEMBER_LIST_UPDATE", d)
    assert [m["user"]["id"] for m in items] == ["42"]
