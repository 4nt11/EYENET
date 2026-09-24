# SPDX-License-Identifier: AGPL-3.0-or-later
"""Crew clustering: connected components of the shared-infra graph."""

from __future__ import annotations

from uuid import UUID

import pytest

from eyenet.linker.crews import build_crews

A = UUID("00000000-0000-0000-0000-0000000000a1")
B = UUID("00000000-0000-0000-0000-0000000000b2")
C = UUID("00000000-0000-0000-0000-0000000000c3")
D = UUID("00000000-0000-0000-0000-0000000000d4")
E = UUID("00000000-0000-0000-0000-0000000000e5")


@pytest.mark.unit
def test_crew_carries_links_sorted_by_score() -> None:
    edges = [
        (A, B, 0.6, ["handle:wbpay"]),
        (B, C, 0.95, ["handle:lv"]),
        (A, C, 0.8, ["tme:x"]),
    ]
    crews = build_crews(edges)
    assert len(crews) == 1
    crew = crews[0]
    assert crew.edge_count == 3
    assert len(crew.links) == 3  # every pairwise link is retained, not just the count
    assert [round(s, 2) for _, _, s, _ in crew.links] == [0.95, 0.8, 0.6]  # strongest first


@pytest.mark.unit
def test_two_disjoint_crews() -> None:
    edges = [
        (A, B, 0.9, ["handle:wbpay"]),
        (C, D, 0.8, ["handle:lv"]),
    ]
    crews = build_crews(edges)
    assert len(crews) == 2
    memsets = [set(c.members) for c in crews]
    assert {A, B} in memsets and {C, D} in memsets


@pytest.mark.unit
def test_bridge_edge_merges_into_one_crew() -> None:
    # A-B and B-C share actor B (and the bridging handle) -> one crew of 3.
    edges = [
        (A, B, 0.9, ["handle:wbpay_mm1888"]),
        (B, C, 0.7, ["handle:wbpay_mm1888"]),
    ]
    crews = build_crews(edges)
    assert len(crews) == 1
    c = crews[0]
    assert set(c.members) == {A, B, C}
    assert c.edge_count == 2
    assert c.max_score == 0.9
    assert c.top_infra[0] == "handle:wbpay_mm1888"


@pytest.mark.unit
def test_sorted_by_size_then_score() -> None:
    edges = [
        (A, B, 0.5, ["x"]),
        (B, C, 0.5, ["x"]),  # crew {A,B,C} size 3
        (D, E, 0.99, ["y"]),  # crew {D,E} size 2, higher score
    ]
    crews = build_crews(edges)
    assert [len(c.members) for c in crews] == [3, 2]  # larger crew first


@pytest.mark.unit
def test_empty() -> None:
    assert build_crews([]) == []
