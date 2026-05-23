"""MODELS §2.18 — SystemLog allowlist is a frozenset of dotted, lowercase names."""

from __future__ import annotations

import pytest

from eyenet.contracts.syslog import SYSLOG_ALLOWLIST


@pytest.mark.contract
def test_allowlist_is_frozenset() -> None:
    assert isinstance(SYSLOG_ALLOWLIST, frozenset)
    assert len(SYSLOG_ALLOWLIST) > 0


@pytest.mark.contract
def test_entries_are_dotted_lowercase() -> None:
    for name in SYSLOG_ALLOWLIST:
        assert name == name.lower(), f"non-lowercase entry: {name!r}"
        assert "." in name, f"expected dotted name: {name!r}"
        assert " " not in name, f"whitespace in: {name!r}"
        assert name.strip() == name


@pytest.mark.contract
def test_no_duplicates_after_lowercasing() -> None:
    # frozenset already enforces uniqueness, but sanity-check the source.
    assert len({n.lower() for n in SYSLOG_ALLOWLIST}) == len(SYSLOG_ALLOWLIST)
