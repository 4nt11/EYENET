# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure-scorer tests for eyenet.stealer.classifier.

The scorer is intentionally decoupled from ClickHouse: the catalog is
injected and the evidence set is a dataclass. These tests cover the
weighting algorithm, the regularization denominator (K), floor
enforcement, anti-signals, ordering + tiebreaks, and runner-up
emission."""

from __future__ import annotations

import pytest

from eyenet.stealer.classifier import (
    SIGNAL_DENOMINATOR_K,
    ClassificationResult,
    VictimEvidence,
    classify,
)

pytestmark = pytest.mark.unit


def _ev(
    *,
    files: list[str] | None = None,
    paths: list[str] | None = None,
    rules: list[str] | None = None,
    build_tag: str = "",
) -> VictimEvidence:
    return VictimEvidence(
        files=frozenset((f or "").lower() for f in (files or [])),
        paths=frozenset((p or "").lower() for p in (paths or [])),
        rule_ids=frozenset((r or "").lower() for r in (rules or [])),
        build_tag=build_tag,
    )


def _fam(
    slug: str,
    *,
    files: list[str] | None = None,
    paths: list[str] | None = None,
    rules: list[str] | None = None,
    build_tag_regex: str | None = None,
    anti_files: list[str] | None = None,
    anti_rules: list[str] | None = None,
    floor: float = 0.35,
    year: int = 2020,
) -> dict[str, object]:
    out: dict[str, object] = {
        "slug": slug,
        "kind": "stealer",
        "first_seen_year": year,
        "confidence_floor": floor,
    }
    if files is not None:
        out["signature_files"] = files
    if paths is not None:
        out["signature_paths"] = paths
    if rules is not None:
        out["signature_rule_ids"] = rules
    if build_tag_regex is not None:
        out["build_tag_regex"] = build_tag_regex
    if anti_files is not None:
        out["antisignature_files"] = anti_files
    if anti_rules is not None:
        out["antisignature_rule_ids"] = anti_rules
    return out


def test_single_signal_family_cannot_claim_on_one_match() -> None:
    """The regularization K stops a terse family from scoring 1.0 on a
    single sig_file match. Fix for the live-corpus `acr` over-confidence."""
    fam = _fam("single", files=["Info.txt"], floor=0.35)
    ev = _ev(files=["Info.txt"])
    r = classify(ev, catalog=[fam])
    # max_score = 1.0 (one sig_file); score = 1.0; normalized = 1/(1+K).
    expected = 1.0 / (1.0 + SIGNAL_DENOMINATOR_K)
    assert r.verdict is None  # below default 0.35 floor
    assert r.runners_up[0].confidence == pytest.approx(expected, abs=0.001)


def test_rich_family_matches_cleanly() -> None:
    fam = _fam(
        "rich",
        files=["System.txt", "Passwords.txt"],
        rules=["environment_windows", "passwords_block_upper"],
        floor=0.35,
    )
    ev = _ev(
        files=["System.txt", "Passwords.txt"],
        rules=["environment_windows", "passwords_block_upper"],
    )
    r = classify(ev, catalog=[fam])
    assert r.verdict is not None
    assert r.verdict.slug == "rich"
    # All 4 signals match. Positive weights: 2*1.0 + 2*2.0 = 6.0. max_score=6.0.
    # confidence = 6.0 / (6.0 + K) = 6/8 = 0.75.
    assert r.verdict.confidence == pytest.approx(0.75, abs=0.001)
    assert len(r.verdict.evidence) == 4


def test_build_tag_regex_signal() -> None:
    fam = _fam(
        "vidar_like",
        files=["information.txt"],
        build_tag_regex=r"^mix$",
        floor=0.35,
    )
    ev = _ev(files=["information.txt"], build_tag="mix")
    r = classify(ev, catalog=[fam])
    # weights: 1.0 + 5.0 = 6.0 max; both match; score = 6.0; conf = 6/8 = 0.75.
    assert r.verdict is not None
    assert "build_tag:^mix$" in r.verdict.evidence


def test_anti_signal_subtracts() -> None:
    fam = _fam(
        "hate_lumma",
        files=["System.txt", "Environment.txt"],
        anti_files=["information.txt"],
        floor=0.1,
    )
    ev = _ev(files=["System.txt", "Environment.txt", "information.txt"])
    r = classify(ev, catalog=[fam])
    # max = 2.0; raw score = 2 - 2 = 0; conf = 0.
    assert r.runners_up[0].confidence == 0.0
    assert any(e.startswith("anti_file:") for e in r.runners_up[0].evidence)


def test_ordering_breaks_ties_by_year_then_slug() -> None:
    fam_older = _fam("aaa_older", files=["X.txt"], year=2018, floor=0.1)
    fam_newer = _fam("zzz_newer", files=["X.txt"], year=2024, floor=0.1)
    ev = _ev(files=["X.txt"])
    r = classify(ev, catalog=[fam_older, fam_newer])
    # Tie on confidence + evidence length -> newer wins the year tiebreak.
    assert r.runners_up or r.verdict  # at least one ranked
    ranked = [r.verdict.slug] if r.verdict else []
    ranked += [v.slug for v in r.runners_up]
    assert ranked[0] == "zzz_newer"
    assert ranked[1] == "aaa_older"


def test_floor_applied_per_family() -> None:
    low = _fam("permissive", files=["X.txt", "Y.txt"], floor=0.1)
    high = _fam("strict", files=["X.txt", "Y.txt"], floor=0.9)
    ev = _ev(files=["X.txt", "Y.txt"])
    r = classify(ev, catalog=[low, high])
    # Tied on raw confidence, high-floor loses. The verdict goes to the
    # first one by ordering that clears its floor.
    assert r.verdict is not None
    assert r.verdict.slug == "permissive"


def test_no_verdict_when_catalog_empty() -> None:
    ev = _ev(files=["anything.txt"])
    r = classify(ev, catalog=[])
    assert r == ClassificationResult(verdict=None, runners_up=[])


def test_family_with_no_positive_signals_is_skipped() -> None:
    # anti-only family is nonsense; the scorer drops it instead of
    # dividing by zero.
    fam = _fam("anti_only", anti_files=["X.txt"], floor=0.0)
    ev = _ev(files=["X.txt"])
    r = classify(ev, catalog=[fam])
    assert r.verdict is None
    assert r.runners_up == []


def test_path_signal_substring_match() -> None:
    fam = _fam("path_matcher", paths=["Browser/Cookies/"], floor=0.1)
    ev = _ev(paths=["some/path/Browser/Cookies/edge_default.txt"])
    r = classify(ev, catalog=[fam])
    assert r.verdict is not None
    assert any(e.startswith("sig_path:") for e in r.verdict.evidence)


def test_signature_files_trailing_slash_promoted_to_path() -> None:
    # Legacy catalog shape: signature_files: ['Autofill/'] means
    # directory-presence, matched as a path signal, not a file signal.
    fam = _fam("legacy", files=["Autofill/"], floor=0.1)
    ev_file = _ev(files=["Autofill/"])  # bogus: trailing-slash file
    r_file = classify(ev_file, catalog=[fam])
    # files frozenset dropped the trailing-slash entry because
    # _normalize_files excludes it; but classify treats signature_files
    # with trailing slash as a path signal regardless.
    assert r_file.verdict is None  # no path matches

    ev_path = _ev(paths=["/some/root/Autofill/"])
    r_path = classify(ev_path, catalog=[fam])
    assert r_path.verdict is not None  # promoted to sig_path and matched
