# SPDX-License-Identifier: AGPL-3.0-or-later
"""Infostealer-creds enrichments + the per-enrichment scope gate (no-auth-bypass)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.enrichments.registry import REGISTRY, discover
from eyenet.enrichments.remote import stealer_creds as mod
from eyenet.stealer.query import CredRow

pytestmark = pytest.mark.unit


def test_every_enrichment_carries_a_scope_matching_its_output() -> None:
    """Defense-in-depth: no enrichment surfaces an output type without the read scope
    for it (artifact/attachment/thread ride the read:search baseline + tier gate)."""
    discover()
    expect = {
        "message": "read:observations",
        "actor": "read:actors",
        "persona": "read:personas",
        "incident": "read:incidents",
        "source": "read:sources",
        "group": "read:groups",
    }
    for e in REGISTRY.values():
        assert e.effective_scope == expect.get(e.output_type, e.required_scope)
    # The creds enrichments explicitly require read:stealer, overriding the artifact default.
    assert REGISTRY[("artifact", "infostealer_domain")].effective_scope == "read:stealer"
    assert REGISTRY[("artifact", "infostealer_subdomain")].effective_scope == "read:stealer"


def test_has_subdomain_splits_domain_from_subdomain() -> None:
    assert mod._has_subdomain("gov.fiction.cl") is True
    assert mod._has_subdomain("mail.gov.fiction.cl") is True
    assert mod._has_subdomain("fiction.cl") is False
    assert mod._has_subdomain("example.com") is False


def test_cred_node_shape() -> None:
    node = mod._cred_node(
        CredRow(host="accounts.google.com", url="https://x", login="v@x.com",
                password="hunter2", scheme="https", tld="com")
    )
    assert node.entity_type == "artifact"
    assert node.title == "v@x.com"  # login is the lead
    assert node.fields["kind"] == "credential"
    assert node.fields["password"] == "hunter2"
    assert node.fields["ephemeral"] is True
    # Stable id across calls (same host|login|password).
    assert node.entity_id == mod._cred_node(
        CredRow(host="accounts.google.com", url="https://y", login="v@x.com",
                password="hunter2", scheme="https", tld="com")
    ).entity_id


async def test_fetch_builds_nodes_and_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        CredRow("fiction.cl", "https://fiction.cl", "admin", "pw1", "https", "cl"),
        CredRow("fiction.cl", "https://fiction.cl", "user", "pw2", "https", "cl"),
    ]
    monkeypatch.setattr(mod._reader, "search", lambda **_k: rows)
    monkeypatch.setattr(mod._reader, "count_host", lambda _h: 2)
    src = uuid4()
    res = await mod._fetch_creds(src, "fiction.cl", limit=10, offset=0, want_total=True)
    assert [n.title for n in res.nodes] == ["admin", "user"]
    assert all(e["src_id"] == src and e["kind"] == "infostealer_leak" for e in res.edges)
    assert res.total == 2
    assert res.has_more is False


async def test_fetch_has_more_on_overfetch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reader is asked for limit+1; 3 back for limit 2 => has_more, page trimmed to 2.
    rows = [CredRow(f"h{i}", "", f"u{i}", "p", "https", "") for i in range(3)]
    monkeypatch.setattr(mod._reader, "search", lambda **_k: rows)
    res = await mod._fetch_creds(uuid4(), "h", limit=2, offset=0, want_total=False)
    assert len(res.nodes) == 2
    assert res.has_more is True
    assert res.total is None
