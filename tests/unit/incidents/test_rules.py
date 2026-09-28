# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator rule compile / validate / match (pure — no model, no storage)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eyenet.incidents import rules

pytestmark = pytest.mark.unit


def _rule(name, pattern, label, enabled=True):
    return SimpleNamespace(name=name, pattern=pattern, label=label, enabled=enabled)


def test_validate_pattern_good_and_bad() -> None:
    assert rules.validate_pattern(r"(?i)\bmybooter\b") is None
    assert rules.validate_pattern("(((") is not None  # invalid RE2 -> error message


def test_compile_skips_disabled_and_matches() -> None:
    compiled = rules.compile_rules(
        [
            _rule("op_booter", r"(?i)\bmybooter\b", "tooling"),
            _rule("op_off", r"(?i)\bnope\b", "leak", enabled=False),
        ]
    )
    assert len(compiled) == 1  # disabled skipped
    assert rules.match_labels("selling MyBooter cheap", compiled) == {"tooling"}
    assert rules.match_labels("nothing here", compiled) == set()


def test_match_runs_on_normalized_text() -> None:
    # match_labels normalizes (NFC + confusable fold) before matching, like the prefilter.
    compiled = rules.compile_rules([_rule("op_b", r"(?i)\bbooter\b", "tooling")])
    assert rules.match_labels("cheap BOOTER here", compiled) == {"tooling"}


def test_builtin_names_and_labels() -> None:
    assert "tool_sale" in rules.BUILTIN_SIGNAL_NAMES  # collision guard source
    assert "crimeware_tooling" in rules.TAXONOMY_LABELS
    assert rules.match_labels("x", []) == set()  # empty ruleset short-circuits
