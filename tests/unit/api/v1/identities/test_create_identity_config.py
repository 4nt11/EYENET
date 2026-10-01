# SPDX-License-Identifier: AGPL-3.0-or-later
"""_build_source_config: the forum branch carries forum_user_agent when set."""

from __future__ import annotations

import pytest

from eyenet.api.v1.identities.api_create_identity import _build_source_config
from eyenet.contracts.enums import SourceKind

pytestmark = pytest.mark.unit


def test_forum_config_includes_user_agent_when_set() -> None:
    cfg = _build_source_config(
        SourceKind.FORUM,
        telegram_api_id=None,
        telegram_api_hash=None,
        monitor_groups=None,
        forum_base_url="http://x.onion",
        forum_thread_urls=None,
        forum_user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    )
    assert cfg["forum_base_url"] == "http://x.onion"
    assert cfg["forum_user_agent"].startswith("Mozilla/5.0")  # type: ignore[union-attr]


def test_forum_config_omits_user_agent_when_blank() -> None:
    # Omitted → the collector's Tor Browser default applies; don't write an
    # empty override into source_config.
    cfg = _build_source_config(
        SourceKind.FORUM,
        telegram_api_id=None,
        telegram_api_hash=None,
        monitor_groups=None,
        forum_base_url="http://x.onion",
        forum_thread_urls=None,
        forum_user_agent=None,
    )
    assert "forum_user_agent" not in cfg
