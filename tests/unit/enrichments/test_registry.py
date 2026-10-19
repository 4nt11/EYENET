# SPDX-License-Identifier: AGPL-3.0-or-later
"""Enrichment autodiscovery + registry: the 16 built-ins register with correct
metadata, a dropped-in subclass is discovered without editing any dispatch, and
unknown lookups fail the way the graph-expand callers expect."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from eyenet.enrichments import LocalSQLEnrichment
from eyenet.enrichments.registry import (
    REGISTRY,
    discover,
    enrichments_for_src_type,
    get_enrichment,
)

pytestmark = pytest.mark.unit

# (src_type, name) -> (output_type, edge_kind, single, tier_gated)
_EXPECTED: dict[tuple[str, str], tuple[str, str, bool, bool]] = {
    ("actor", "messages"): ("message", "authored", False, False),
    ("actor", "artifacts"): ("artifact", "uses_infra", False, False),
    ("actor", "groups"): ("group", "active_in", False, False),
    ("actor", "linked"): ("actor", "linked", False, False),
    ("actor", "related"): ("actor", "related", False, False),
    ("artifact", "messages"): ("message", "mentioned_in", False, False),
    ("artifact", "actors"): ("actor", "mentioned_by", False, False),
    ("message", "author"): ("actor", "authored_by", True, False),
    ("message", "container"): ("group", "in", True, False),
    ("message", "artifacts"): ("artifact", "mentions", False, False),
    ("thread", "messages"): ("message", "in_thread", False, False),
    ("thread", "participants"): ("actor", "posted_in", False, False),
    ("thread", "op"): ("actor", "started", True, False),
    ("group", "messages"): ("message", "in_group", False, False),
    ("group", "participants"): ("actor", "active_in", False, False),
    ("document", "artifacts"): ("artifact", "contains_artifact", False, True),
    ("persona", "actors"): ("actor", "member", False, False),
    ("persona", "messages"): ("message", "authored", False, False),
    ("persona", "artifacts"): ("artifact", "uses_infra", False, False),
    ("persona", "wallets"): ("artifact", "uses_infra", False, False),
    ("persona", "groups"): ("group", "active_in", False, False),
    ("actor", "started"): ("thread", "started", False, False),
    ("actor", "replied_in"): ("thread", "replied_in", False, False),
    ("actor", "source"): ("source", "from_source", True, False),
    ("message", "source"): ("source", "from_source", True, False),
    ("group", "source"): ("source", "from_source", True, False),
    ("thread", "source"): ("source", "from_source", True, False),
    ("artifact", "domain"): ("artifact", "on_domain", True, False),
    ("message", "incidents"): ("incident", "classified_as", False, False),
    ("thread", "incidents"): ("incident", "has_incident", False, False),
    ("actor", "incidents"): ("incident", "has_incident", False, False),
    ("message", "attachments"): ("attachment", "attached", False, False),
    ("actor", "attachments"): ("attachment", "posted", False, False),
}


def test_builtins_register_with_correct_metadata() -> None:
    discover()
    for (src, name), (output_type, edge_kind, single, tier_gated) in _EXPECTED.items():
        enr = get_enrichment(src, name)
        assert enr.output_type == output_type, (src, name)
        assert enr.edge_kind == edge_kind, (src, name)
        assert enr.single is single, (src, name)
        assert enr.tier_gated is tier_gated, (src, name)


def test_builtin_count_matches_expected() -> None:
    discover()
    builtin = [
        e for e in REGISTRY.values() if type(e).__module__.startswith("eyenet.enrichments.builtins")
    ]
    assert len(builtin) == len(_EXPECTED) == 33


def test_for_src_type_groups_by_source() -> None:
    discover()
    actor_names = {e.name for e in enrichments_for_src_type("actor")}
    assert {"messages", "artifacts", "groups", "linked", "related"} <= actor_names
    assert enrichments_for_src_type("nope") == []


def test_unknown_enrichment_raises() -> None:
    with pytest.raises(ValueError, match="unknown enrichment"):
        get_enrichment("actor", "nope")


def test_dropped_in_subclass_is_discovered_without_editing_dispatch() -> None:
    # A contributor drops a concrete LocalSQLEnrichment anywhere; autodiscovery
    # (which walks every concrete Enrichment subclass) registers it on the next
    # discover(force=True) with no change to any central catalog.
    class DemoEnrichment(LocalSQLEnrichment):
        src_type = "demo_src"
        name = "demo"
        output_type = "actor"
        edge_kind = "demo_edge"

        def build_select(self, src_id: UUID) -> tuple[Any, Any]:  # pragma: no cover
            raise NotImplementedError

    try:
        discover(force=True)
        got = get_enrichment("demo_src", "demo")
        assert isinstance(got, DemoEnrichment)
    finally:
        REGISTRY.pop(("demo_src", "demo"), None)
