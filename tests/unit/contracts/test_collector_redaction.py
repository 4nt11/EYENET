"""Tests for :func:`eyenet.contracts.collector.redact_config` (API_PLAN §4.11.4)."""

from __future__ import annotations

import pytest

from eyenet.contracts.collector import redact_config


@pytest.mark.unit
def test_redact_returns_full_blob_with_grant() -> None:
    config = {
        "kind": "telegram",
        "monitor_chat_ids": [-100, -101],
        "rate_limit_per_min": 60,
    }
    assert redact_config(config, has_read_grant=True) == config


@pytest.mark.unit
def test_redact_strips_body_without_grant() -> None:
    config = {
        "kind": "telegram",
        "monitor_chat_ids": [-100, -101],
        "rate_limit_per_min": 60,
        "proxy_uri_override": "socks5://user:pass@host:1080",
    }
    redacted = redact_config(config, has_read_grant=False)
    assert redacted == {"__redacted__": True, "kind": "telegram"}
    assert "monitor_chat_ids" not in redacted
    assert "proxy_uri_override" not in redacted


@pytest.mark.unit
def test_redact_preserves_kind_discriminator() -> None:
    # Matrix collectors get the same treatment.
    redacted = redact_config(
        {"kind": "matrix", "monitor_rooms": ["#x:y"], "homeserver_url": "https://h"},
        has_read_grant=False,
    )
    assert redacted == {"__redacted__": True, "kind": "matrix"}


@pytest.mark.unit
def test_redact_missing_kind_still_marks_redacted() -> None:
    # Malformed config without ``kind`` — the redacted shape must STILL
    # carry __redacted__=True so consumers never confuse a stripped
    # blob for a fully-readable one.
    redacted = redact_config({"surprise": 1}, has_read_grant=False)
    assert redacted == {"__redacted__": True}


@pytest.mark.unit
def test_redact_does_not_mutate_input() -> None:
    config = {"kind": "telegram", "monitor_chat_ids": [-100]}
    original = dict(config)
    redact_config(config, has_read_grant=False)
    redact_config(config, has_read_grant=True)
    assert config == original


@pytest.mark.unit
def test_redact_returns_distinct_dict_no_aliasing() -> None:
    config = {"kind": "telegram"}
    redacted = redact_config(config, has_read_grant=False)
    redacted["junk"] = 1
    assert "junk" not in config
