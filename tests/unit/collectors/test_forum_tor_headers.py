# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum collector Tor/onion header profile + Referer threading (tradecraft).

Guards the browser-impersonation surface: a bare UA / missing Accept / no
Referer chain fingerprints a crawler, and (over Tor) a UA inconsistent with the
cookie-minting Tor Browser session is a ban signal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eyenet.collectors.forum.real import (
    _BASE_HEADERS,
    _DEFAULT_USER_AGENT,
    MyBBForumCollector,
)
from eyenet.contracts.enums import SourceKind
from eyenet.identity_pool import IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump


@pytest.mark.unit
def test_nav_headers_fresh_navigation_is_sec_fetch_none() -> None:
    assert MyBBForumCollector._nav_headers(None) == {"Sec-Fetch-Site": "none"}


@pytest.mark.unit
def test_nav_headers_with_referer_is_same_origin() -> None:
    h = MyBBForumCollector._nav_headers("http://host.onion/Forum-Databases")
    assert h == {
        "Referer": "http://host.onion/Forum-Databases",
        "Sec-Fetch-Site": "same-origin",
    }


@pytest.mark.unit
def test_default_user_agent_is_tor_browser_firefox_esr() -> None:
    # Tor Browser is Firefox-based; the default must NOT be a Chrome string
    # (Chrome without Sec-CH-UA client hints is itself a synthetic tell).
    assert "Firefox/" in _DEFAULT_USER_AGENT
    assert "Gecko" in _DEFAULT_USER_AGENT
    assert "Chrome/" not in _DEFAULT_USER_AGENT


@pytest.mark.unit
def test_base_headers_profile_invariants() -> None:
    # Present: the static Tor Browser navigation headers.
    for k in (
        "Accept",
        "Accept-Language",
        "Sec-GPC",
        "Upgrade-Insecure-Requests",
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-User",
        "Priority",
    ):
        assert k in _BASE_HEADERS
    assert _BASE_HEADERS["Accept"].startswith("text/html,application/xhtml+xml")
    # Absent on purpose: UA is per-identity; Accept-Encoding is left to httpx
    # (so it only advertises codecs it can decode); Sec-Fetch-Site is per-request.
    assert "User-Agent" not in _BASE_HEADERS
    assert "Accept-Encoding" not in _BASE_HEADERS
    assert "Sec-Fetch-Site" not in _BASE_HEADERS


@pytest.mark.unit
def test_identity_entry_accepts_and_dumps_forum_user_agent(tmp_path: Path) -> None:
    ua = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
    entry = IdentityFileEntry(
        name="pwnforums",
        source=SourceKind.FORUM,
        forum_base_url="http://pwnfrm7rbf.onion",
        forum_user_agent=ua,
        proxy_uri="socks5h://tor:9050",
    )
    assert entry.forum_user_agent == ua
    out = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), out)
    text = out.read_text(encoding="utf-8")
    assert f'forum_user_agent = "{ua}"' in text
    assert 'proxy_uri = "socks5h://tor:9050"' in text
