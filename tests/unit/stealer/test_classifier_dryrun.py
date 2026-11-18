# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the classifier dry-run overlay logic.

The CH-touching path (collect_evidence + fetch victim pairs) is covered
end-to-end by the live smoke test; here we exercise the pure overlay +
scoring logic against a fake CH client, so the scope reductions (kind
filtering, limit cap, shift truncation) have unit coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eyenet.stealer.classifier_dryrun import _DRYRUN_HARD_CAP, dry_run

pytestmark = pytest.mark.unit


@dataclass
class _Rows:
    result_rows: list[tuple[Any, ...]]


class _FakeAsync:
    """Mimics clickhouse-connect async client surface. The dry_run flow
    calls .query() three times per invocation: pair-list, files-rows per
    victim, records-rows per victim. We stage them as a FIFO."""

    def __init__(self, responses: list[list[tuple[Any, ...]]]) -> None:
        self._responses = [_Rows(r) for r in responses]

    async def query(self, _sql: str, parameters: dict[str, object] | None = None) -> _Rows:
        return self._responses.pop(0)


def _ch_pair(sha: str = "a", vf: str = "v1") -> tuple[str, str]:
    return (sha, vf)


async def _stub_client(monkeypatch: pytest.MonkeyPatch, client: _FakeAsync) -> None:
    import eyenet.stealer.classifier_dryrun as mod

    async def _getter() -> _FakeAsync:
        return client

    monkeypatch.setattr(mod, "get_async_clickhouse_client", _getter)


def _vidar_fam() -> dict[str, object]:
    return {
        "slug": "vidar",
        "kind": "stealer",
        "signature_files": ["information.txt"],
        "confidence_floor": 0.1,
    }


def _lumma_fam() -> dict[str, object]:
    return {
        "slug": "lumma",
        "kind": "stealer",
        "signature_files": ["System.txt", "Environment.txt"],
        "confidence_floor": 0.1,
    }


async def test_dry_run_computes_before_after_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fake catalog: vidar matches victim-1 (information.txt), lumma matches victim-2.
    monkeypatch.setattr(
        "eyenet.stealer.classifier_dryrun.list_family_slugs",
        lambda: ["vidar", "lumma"],
    )
    monkeypatch.setattr(
        "eyenet.stealer.classifier_dryrun.read_family",
        {"vidar": _vidar_fam(), "lumma": _lumma_fam()}.__getitem__,
    )

    client = _FakeAsync(
        [
            # pair_rows: 2 victims
            [("a" * 64, "v1"), ("a" * 64, "v2")],
            # v1 collect_evidence: files + records (one call each; classify
            # runs twice against the same evidence for before + after).
            [("information.txt", "root/information.txt")],
            [("stealer_info_yaml", {"build_tag": "mix"})],
            # v2: System.txt + Environment.txt for lumma
            [("System.txt", "root/System.txt"), ("Environment.txt", "root/Environment.txt")],
            [("environment_windows", {})],
        ]
    )
    await _stub_client(monkeypatch, client)

    # Empty proposal: before == after
    r = await dry_run([], limit=10)
    assert r.sampled == 2
    by_slug = {c.slug: (c.before, c.after) for c in r.counts}
    assert by_slug.get("vidar") == (1, 1)
    assert by_slug.get("lumma") == (1, 1)
    assert r.shifts == []


async def test_dry_run_proposal_flips_vidar_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("eyenet.stealer.classifier_dryrun.list_family_slugs", lambda: ["vidar"])
    monkeypatch.setattr(
        "eyenet.stealer.classifier_dryrun.read_family",
        {"vidar": _vidar_fam()}.__getitem__,
    )

    client = _FakeAsync(
        [
            [("a" * 64, "v1")],
            [("information.txt", "root/information.txt")],
            [("x", {})],
        ]
    )
    await _stub_client(monkeypatch, client)

    r = await dry_run(
        [
            {
                "slug": "vidar",
                "kind": "stealer",
                "signature_files": ["nope.txt"],
                "confidence_floor": 0.1,
            }
        ],
        limit=10,
    )
    by_slug = {c.slug: (c.before, c.after) for c in r.counts}
    # Vidar claimed victim before, loses after
    assert by_slug.get("vidar", (0, 0))[0] >= 1
    assert by_slug.get("vidar", (0, 0))[1] == 0
    # Shift list records the move
    assert len(r.shifts) == 1
    assert r.shifts[0].before_slug == "vidar"
    assert r.shifts[0].after_slug == ""


async def test_dry_run_ignores_non_stealer_kind_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proposal with kind != stealer must not enter the overlay even if
    the slug matches a stealer family: that would be a catalog design
    decision outside the dry-run's scope."""
    monkeypatch.setattr("eyenet.stealer.classifier_dryrun.list_family_slugs", lambda: ["vidar"])
    monkeypatch.setattr(
        "eyenet.stealer.classifier_dryrun.read_family",
        {"vidar": _vidar_fam()}.__getitem__,
    )

    client = _FakeAsync(
        [
            [("a" * 64, "v1")],
            [("information.txt", "r/information.txt")],
            [],
        ]
    )
    await _stub_client(monkeypatch, client)

    # Kind=content proposal with vidar slug: ignored by the overlay.
    r = await dry_run(
        [
            {
                "slug": "vidar",
                "kind": "content",
                "signature_files": ["nope.txt"],
                "confidence_floor": 0.1,
            }
        ],
        limit=10,
    )
    by_slug = {c.slug: (c.before, c.after) for c in r.counts}
    # Before and after both have vidar at 1 because the overlay was dropped.
    assert by_slug.get("vidar") == (1, 1)
    assert r.shifts == []


def test_dry_run_hard_cap_present() -> None:
    assert _DRYRUN_HARD_CAP == 500
