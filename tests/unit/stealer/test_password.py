# SPDX-License-Identifier: AGPL-3.0-or-later
"""parse_password: anchor search, homoglyph defang, link/handle/literal, candidates."""

from __future__ import annotations

import pytest

from eyenet.stealer.password import parse_password, password_candidates

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("body", "kind", "channel"),
    [
        ("\U0001f510Pass: t.me/CartelJohnDoe \U0001f420", "channel_link", "CartelJohnDoe"),
        ("Pass: @CloudHesoyam  Reserve Channel", "channel_link", "CloudHesoyam"),
        ("pass - @KhazanCloud ✅ Contact the admin - @BuzzLPlanet", "channel_link", "KhazanCloud"),
        ("\U0001f39a️ Password: t.me/LolzTeamCloud\n======", "channel_link", "LolzTeamCloud"),
        ("Pass: Xk9mPq2secret end", "literal", None),
        ("FRESH LINK  t.me/SlurmLogs t.me/SlurmLogs t.me/SlurmLogs", "link_only", "SlurmLogs"),
        ("Fresh Link https://t.me/+pqf4PyqnkUg5NTAx", "invite_only", "+pqf4PyqnkUg5NTAx"),
        # homoglyph evasion: Cyrillic 'а' in pаss
        ("Subscribe  pаss: https://t.me/WichLoveFromR  Рrivate", "channel_link", "WichLoveFromR"),
        # no-delimiter "Pass <link>"
        ("\U0001f510Pass https://t.me/RogueCloud \U0001f420", "channel_link", "RogueCloud"),
    ],
)
def test_parse_hits(body: str, kind: str, channel: str | None) -> None:
    got = parse_password(body)
    assert got is not None
    assert (got.kind, got.channel) == (kind, channel)


@pytest.mark.parametrize(
    "body",
    [
        "just a footer with no link at all",
        "these files are password protected lol",  # no delim, not a link -> drop
        "DARKSIDE NEW FIL3  LINK TO NEW UPLOAD  News  Reviews",  # banner, no Pass
        "",
    ],
)
def test_parse_misses(body: str) -> None:
    assert parse_password(body) is None


def test_candidates_handle_with_at_first() -> None:
    # The proven real case: "@CloudHesoyam" (with @) opens the RAR; bare does not.
    parsed = parse_password("Pass: @CloudHesoyam  Reserve Channel")
    assert password_candidates(parsed) == ["@CloudHesoyam", "CloudHesoyam"]


def test_candidates_empty_for_link_only_and_none() -> None:
    # link_only (password inferred, not labeled) and no-match both yield no password to try.
    assert password_candidates(parse_password("FRESH LINK t.me/SlurmLogs")) == []
    assert password_candidates(None) == []
