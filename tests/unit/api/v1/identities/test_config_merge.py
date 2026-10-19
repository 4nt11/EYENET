# SPDX-License-Identifier: AGPL-3.0-or-later
"""apply_config_updates — validate + merge editable identity collector config.

The forum fingerprint/evasion fields are load-bearing (CLAUDE.md §4a); a bad value must
be a loud error, never a silent fall-through. Only client-sent fields are touched."""

from __future__ import annotations

import pytest

from eyenet.api.deps import UnprocessableError
from eyenet.api.v1.identities._config import apply_config_updates
from eyenet.contracts.enums import SourceKind

pytestmark = pytest.mark.unit


def test_only_sent_fields_merge_rest_preserved() -> None:
    existing = {"forum_base_url": "https://b.onion", "forum_engine": "mybb", "secret_x": "keep"}
    out = apply_config_updates(SourceKind.FORUM, existing, {"forum_engine": "xenforo"})
    assert out["forum_engine"] == "xenforo"
    assert out["forum_base_url"] == "https://b.onion"  # untouched
    assert out["secret_x"] == "keep"  # non-editable keys preserved


def test_evasion_level_expands_pacing() -> None:
    out = apply_config_updates(SourceKind.FORUM, {}, {"forum_evasion_level": "ghost"})
    assert out["forum_evasion_level"] == "ghost"
    assert out["forum_delay_min"] > 0 and out["forum_delay_max"] >= out["forum_delay_min"]
    assert "forum_discovery_depth" in out


def test_bad_evasion_level_rejected() -> None:
    with pytest.raises(UnprocessableError):
        apply_config_updates(SourceKind.FORUM, {}, {"forum_evasion_level": "turbo"})


def test_bad_impersonate_target_rejected() -> None:
    with pytest.raises(UnprocessableError):
        apply_config_updates(SourceKind.FORUM, {}, {"forum_tls_impersonate": "chrome999"})


def test_empty_string_clears_clearable() -> None:
    existing = {"forum_user_agent": "Mozilla/5.0", "forum_tls_impersonate": "firefox147"}
    out = apply_config_updates(SourceKind.FORUM, existing, {"forum_user_agent": ""})
    assert "forum_user_agent" not in out
    assert out["forum_tls_impersonate"] == "firefox147"  # untouched


def test_bad_engine_rejected() -> None:
    with pytest.raises(UnprocessableError):
        apply_config_updates(SourceKind.FORUM, {}, {"forum_engine": "notaforum"})


def test_delay_min_gt_max_rejected() -> None:
    with pytest.raises(UnprocessableError):
        apply_config_updates(SourceKind.FORUM, {}, {"forum_delay_min": 20, "forum_delay_max": 5})


def test_telegram_monitor_groups_merge() -> None:
    out = apply_config_updates(
        SourceKind.TELEGRAM,
        {"telegram_api_hash": "secret"},
        {"monitor_groups": [" @a ", "", "b"]},
    )
    assert out["monitor_groups"] == ["@a", "b"]  # trimmed, blanks dropped
    assert out["telegram_api_hash"] == "secret"  # secret preserved
