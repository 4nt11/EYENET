# SPDX-License-Identifier: AGPL-3.0-or-later
"""_authorship: forwards attribute to the origin; channels aren't individuals."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from telethon.tl.types import PeerChannel, PeerUser, User

from eyenet.collectors.telegram.real import _authorship, _group_platform_id


def _msg(sender_id: int, fwd: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(sender_id=sender_id, fwd_from=fwd)


@pytest.mark.unit
def test_group_platform_id_canonical() -> None:
    # Public group -> @username; else the raw POSITIVE id (never the -100 form),
    # so ingest and enumerate agree on one row per group.
    assert _group_platform_id("cvv190logs", 3573398394) == "@cvv190logs"
    assert _group_platform_id(None, 3914110555) == "3914110555"


@pytest.mark.unit
def test_plain_user_post_is_individual() -> None:
    sender = User(id=123, first_name="Alice", last_name=None, username="alice")
    a = _authorship(_msg(123), sender)
    assert a.platform_userid == "123"
    assert a.handle == "@alice"
    assert a.display_name == "Alice"
    assert not a.is_forward
    assert not a.is_channel_author
    assert a.relayed_by_platform_userid is None
    assert not a.is_bot


@pytest.mark.unit
def test_user_bot_flag_captured() -> None:
    sender = User(id=99, first_name="Rose", last_name=None, username="MissRose_bot", bot=True)
    a = _authorship(_msg(99), sender)
    assert a.is_bot
    # A forward's origin bot status is unknown → never asserted as a bot.
    fwd = SimpleNamespace(from_id=PeerUser(99), from_name="Rose")
    assert not _authorship(_msg(-100123, fwd), SimpleNamespace()).is_bot


@pytest.mark.unit
def test_channel_broadcast_is_not_individual() -> None:
    # Non-forward, sender is the channel (not a User) → channel-broadcast.
    a = _authorship(_msg(-1003573398394), SimpleNamespace())
    assert a.is_channel_author
    assert not a.is_forward
    assert a.platform_userid == "-1003573398394"


@pytest.mark.unit
def test_forward_from_person_credits_the_person() -> None:
    fwd = SimpleNamespace(from_id=PeerUser(555), from_name="Bob")
    a = _authorship(_msg(-1003928209947, fwd), SimpleNamespace())  # reposted by a channel
    assert a.is_forward
    assert not a.is_channel_author  # the ORIGIN is a person
    assert a.platform_userid == "555"  # credited to the person, not the relay
    assert a.display_name == "Bob"
    assert a.relayed_by_platform_userid == "-1003928209947"  # relay recorded


@pytest.mark.unit
def test_forward_from_channel_is_channel_origin() -> None:
    fwd = SimpleNamespace(from_id=PeerChannel(3928209947), from_name=None)
    a = _authorship(_msg(-1003573398394, fwd), SimpleNamespace())
    assert a.is_forward
    assert a.is_channel_author  # origin is a channel
    assert a.platform_userid == "-1003928209947"  # marked channel id of the origin


@pytest.mark.unit
def test_forward_hidden_origin_coalesces_by_name() -> None:
    fwd = SimpleNamespace(from_id=None, from_name="Secret Source")
    a = _authorship(_msg(-1003573398394, fwd), SimpleNamespace())
    assert a.is_forward
    assert a.platform_userid == "fwd:Secret Source"
    assert a.display_name == "Secret Source"
    # A second hidden forward from the same name coalesces to the same actor.
    b = _authorship(_msg(-1009999999999, fwd), SimpleNamespace())
    assert a.actor_key == b.actor_key
