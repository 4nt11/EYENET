# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reaction tallies surfaced on GroupMessage from source_specific (Discord)."""

from __future__ import annotations

import pytest

from eyenet.api.v1.schemas.groups import ReactionTally, _reactions


@pytest.mark.unit
def test_reactions_parses_unicode_and_custom_drops_empty_and_malformed() -> None:
    ss = {
        "reactions": [
            {"emoji": {"name": "🔥", "id": None}, "count": 3},  # unicode -> char
            {"emoji": {"name": "pepe", "id": "123"}, "count": 5},  # custom -> :name:
            {"emoji": {"name": "x", "id": None}, "count": 0},  # zero count dropped
            "garbage",  # non-dict entry ignored
            {"emoji": {"name": "y"}, "count": "nan"},  # bad count -> 0 -> dropped
        ]
    }
    assert _reactions(ss) == [
        ReactionTally(emoji="🔥", count=3),
        ReactionTally(emoji=":pepe:", count=5),
    ]


@pytest.mark.unit
def test_reactions_absent_or_wrong_type_yields_none() -> None:
    assert _reactions({}) == []
    assert _reactions({"reactions": None}) == []
    assert _reactions({"reactions": "not-a-list"}) == []
