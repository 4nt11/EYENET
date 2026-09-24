# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure relation-builder: handle extraction + edge aggregation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.contracts.enums import RelationKind
from eyenet.relations.mentions import (
    RelationInputRow,
    build_relations,
    extract_handles,
    normalize_handle,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def test_extract_handles_lowercases_and_dedupes() -> None:
    assert extract_handles("yo @Alice @alice and @bob_99!") == {"alice", "bob_99"}


def test_extract_handles_ignores_emails_and_too_short() -> None:
    # No leading-space requirement, but an email's local@domain shouldn't match
    # the domain as a handle, and 2-char handles are below the floor.
    assert extract_handles("mail me at name@gmail plus @ok @yes") == {"yes"}


def test_extract_handles_empty() -> None:
    assert extract_handles(None) == set()
    assert extract_handles("") == set()


def test_normalize_handle() -> None:
    assert normalize_handle("@Bob") == "bob"
    assert normalize_handle("Bob") == "bob"
    assert normalize_handle("@") is None
    assert normalize_handle(None) is None


def test_mention_edges_count_and_timespan() -> None:
    a, b = uuid4(), uuid4()
    src = uuid4()
    rows = [
        RelationInputRow(a, "hi @bob", _T0, src, None, None),
        RelationInputRow(a, "@bob again", _T0 + timedelta(hours=1), src, None, None),
    ]
    edges = build_relations(rows, {"bob": b}, {})
    assert len(edges) == 1
    e = edges[0]
    assert (e.from_actor, e.to_actor, e.kind) == (a, b, RelationKind.MENTION)
    assert e.count == 2
    assert e.first_seen == _T0
    assert e.last_seen == _T0 + timedelta(hours=1)


def test_self_mention_and_unknown_handle_dropped() -> None:
    a = uuid4()
    rows = [RelationInputRow(a, "@self and @ghost", _T0, uuid4(), None, None)]
    # self resolves to a (dropped); ghost resolves to nobody (dropped).
    assert build_relations(rows, {"self": a}, {}) == []


def test_forward_edge_is_relayer_to_origin() -> None:
    relayer, origin = uuid4(), uuid4()
    src = uuid4()
    # Post-attribution: message author = origin; relayer recorded as platform id.
    rows = [RelationInputRow(origin, "", _T0, src, origin, "555")]
    edges = build_relations(rows, {}, {"555": relayer})
    assert len(edges) == 1
    e = edges[0]
    assert (e.from_actor, e.to_actor, e.kind) == (relayer, origin, RelationKind.FORWARD)


def test_forward_unresolved_relayer_dropped() -> None:
    origin = uuid4()
    rows = [RelationInputRow(origin, "", _T0, uuid4(), origin, "999")]
    assert build_relations(rows, {}, {}) == []  # 999 not an actor


def test_edges_sorted_by_count_desc() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    src = uuid4()
    rows = [
        RelationInputRow(a, "@bee", _T0, src, None, None),
        RelationInputRow(a, "@cee", _T0, src, None, None),
        RelationInputRow(a, "@cee", _T0, src, None, None),
    ]
    edges = build_relations(rows, {"bee": b, "cee": c}, {})
    assert [e.count for e in edges] == [2, 1]
    assert edges[0].to_actor == c
