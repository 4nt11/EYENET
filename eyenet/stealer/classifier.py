# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-victim stealer-family classifier.

Weighted-signal scorer. The family catalog
(``eyenet/stealer/families/*.yaml``) declares per-family positive and
negative signals (:mod:`eyenet.stealer.families.rw` validates the shape).
This module collects the victim evidence set from ClickHouse, scores every
``kind: stealer`` family against it, and returns a verdict.

See ``development/STEALER_FAMILY_CLASSIFIER_DESIGN.md`` for the full
contract. Non-trivial design calls:

- Signals are matched literally for files/rule_ids (lowercased; filename
  compared, not path) and by substring for paths. Build-tag is regex.
- Per-family score is the sum of matched positive weights minus matched
  anti weights, then normalized by the family's max possible positive
  score so a catalog-rich entry does not unfairly outscore a terse one.
- confidence_floor is enforced AFTER normalization, so a family that
  barely clears a cold-start floor still wins a tie against one that
  cannot clear it at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from eyenet.stealer.families.rw import list_family_slugs, read_family

# Default signal weights. Overridden per-family via the YAML
# `signal_weights` field. Keys match the ones the loader allow-lists
# (eyenet.stealer.families.rw._VALID_SIGNAL_WEIGHT_KEYS).
DEFAULT_WEIGHTS: dict[str, float] = {
    "sig_file": 1.0,
    "sig_path": 1.5,
    "sig_rule": 2.0,
    "build_tag": 5.0,
    "anti_file": -2.0,
    "anti_rule": -2.5,
}

# Default below-this-no-verdict. Overridden per-family via
# `confidence_floor`.
DEFAULT_FLOOR = 0.35

# Regularization constant added to the family's max_score denominator.
# Without it a family declaring one signal that matches one thing scores
# 1.0 after normalization and wins against richer, better-matched
# competitors. With K=2.0 a single sig_file hitting a single file lands
# at 1 / (1 + 2) = 0.33, below the default 0.35 floor, so a terse family
# needs more than one piece of positive evidence to claim a victim.
# Tuned so a signal-dense family matching half its signatures still
# clears a 0.4 floor (e.g. 5/(10+2) = 0.42).
SIGNAL_DENOMINATOR_K = 2.0

# How many runners-up to return alongside the verdict. Shown in the drawer
# popover so the operator sees "stealc 0.74, lumma 0.42, vidar 0.18".
RUNNER_UP_CAP = 3


@dataclass(frozen=True, slots=True)
class VictimEvidence:
    """What we observed about one (archive, victim). Rendered from CH by
    :func:`collect_evidence`; fed to :func:`classify`."""

    files: frozenset[str]
    paths: frozenset[str]
    rule_ids: frozenset[str]
    build_tag: str  # empty string when no build_tag was captured


@dataclass(frozen=True, slots=True)
class FamilyVerdict:
    """A single family's ranking against one victim's evidence set."""

    slug: str
    confidence: float  # 0 .. 1
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Full output. ``verdict`` is the top-ranked family that cleared its
    confidence floor, or None when none did; ``runners_up`` is the next
    few ranked slugs (regardless of floor) so the operator sees the
    scorer's state of mind."""

    verdict: FamilyVerdict | None
    runners_up: list[FamilyVerdict]


def _load_stealer_catalog() -> list[dict[str, Any]]:
    """Return the catalog filtered to ``kind: stealer``. Other kinds are
    not classification targets and would pollute the ranking with low
    scores."""
    out: list[dict[str, Any]] = []
    for slug in list_family_slugs():
        try:
            fam = read_family(slug)
        except (FileNotFoundError, ValueError):
            continue
        if fam.get("kind") == "stealer":
            out.append(fam)
    return out


def _normalize_files(files: list[str]) -> frozenset[str]:
    """Filenames are matched case-folded. Paths with separators are
    reduced to their basename so a file in any directory still matches a
    bare ``Passwords.txt`` signature; the ``signature_paths`` field is the
    right place to express directory structure requirements."""
    return frozenset(f.rsplit("/", 1)[-1].lower() for f in files if f and not f.endswith("/"))


def _normalize_paths(raw: list[str]) -> frozenset[str]:
    """Paths are matched case-folded, substring-style. We keep the full
    original string and let the scorer check ``substr in victim_path``."""
    return frozenset(p.lower() for p in raw if p)


def _signal_matches_file(sig: str, files: frozenset[str]) -> bool:
    # Allow a trailing slash in signature_files to mean "any file under
    # this dir"; the scorer matches it as a path signal instead.
    sig = sig.strip().lower()
    if sig.endswith("/"):
        return False
    return sig in files


def _signal_matches_path(sig: str, paths: frozenset[str]) -> bool:
    sig = sig.strip().lower()
    return any(sig in p for p in paths)


def classify(
    evidence: VictimEvidence,
    *,
    catalog: list[dict[str, Any]] | None = None,
) -> ClassificationResult:
    """Score every stealer-kind family against the evidence. Returns the
    top verdict (if it clears its floor) plus the next few runners-up.

    ``catalog`` is injected for testability; in production it is read
    from the on-disk family catalog once per CLI/service lifetime."""
    fams = catalog if catalog is not None else _load_stealer_catalog()
    scored: list[FamilyVerdict] = []
    for fam in fams:
        verdict = _score_one(fam, evidence)
        if verdict is not None:
            scored.append(verdict)
    # Sort: confidence DESC, then evidence-count DESC as tiebreaker, then
    # catalog first_seen_year DESC (newer families are usually more
    # specific). Catalog order itself is alphabetical by slug; use it as
    # the final deterministic tiebreak.
    year_by_slug = {fam["slug"]: int(fam.get("first_seen_year", 0) or 0) for fam in fams}
    scored.sort(
        key=lambda v: (
            -v.confidence,
            -len(v.evidence),
            -year_by_slug.get(v.slug, 0),
            v.slug,
        )
    )
    if not scored:
        return ClassificationResult(verdict=None, runners_up=[])
    floors = {fam["slug"]: float(fam.get("confidence_floor") or DEFAULT_FLOOR) for fam in fams}
    top = scored[0]
    cleared = top if top.confidence >= floors.get(top.slug, DEFAULT_FLOOR) else None
    # When nothing clears, the top-ranked family is still runner-up data:
    # the operator wants to see the scorer's state of mind, not a blank.
    start = 1 if cleared else 0
    tail = scored[start : start + RUNNER_UP_CAP]
    return ClassificationResult(verdict=cleared, runners_up=tail)


def _score_one(fam: dict[str, Any], ev: VictimEvidence) -> FamilyVerdict | None:  # noqa: PLR0912
    """Compute one family's score + evidence list. Returns None when the
    family declares no positive signals at all (nothing to match against;
    emitting a zero-score runner-up would just be noise)."""
    weights = dict(DEFAULT_WEIGHTS)
    for k, v in (fam.get("signal_weights") or {}).items():
        weights[k] = float(v)

    # Positive signals: files, paths, rule_ids, build_tag.
    sig_files = list(fam.get("signature_files") or [])
    sig_paths = list(fam.get("signature_paths") or [])
    sig_rules = list(fam.get("signature_rule_ids") or [])
    build_tag_rx = fam.get("build_tag_regex")

    # trailing-slash signature_files are promoted to path signals so an
    # entry like `Autofill/` keeps working across the catalog (legacy
    # shape that predates signature_paths).
    for sf in list(sig_files):
        if sf.endswith("/"):
            sig_paths.append(sf)

    score = 0.0
    max_score = 0.0
    evidence: list[str] = []

    for sf in sig_files:
        if sf.endswith("/"):
            continue  # already promoted to a path signal above
        w = weights["sig_file"]
        max_score += max(w, 0.0)
        if _signal_matches_file(sf, ev.files):
            score += w
            evidence.append(f"sig_file:{sf}")

    for sp in sig_paths:
        w = weights["sig_path"]
        max_score += max(w, 0.0)
        if _signal_matches_path(sp, ev.paths):
            score += w
            evidence.append(f"sig_path:{sp}")

    for sr in sig_rules:
        w = weights["sig_rule"]
        max_score += max(w, 0.0)
        if sr.strip().lower() in ev.rule_ids:
            score += w
            evidence.append(f"sig_rule:{sr}")

    if build_tag_rx:
        w = weights["build_tag"]
        max_score += max(w, 0.0)
        if ev.build_tag:
            try:
                if re.search(build_tag_rx, ev.build_tag):
                    score += w
                    evidence.append(f"build_tag:{build_tag_rx}")
            except re.error:
                # loader already validates, but defensive: a bad regex
                # here is a family-author bug, never fatal to the
                # classification run.
                pass

    if max_score <= 0.0:
        return None  # family declared nothing to match; skip.

    # Anti-signals: files + rule_ids. Subtract whether they matched;
    # never counted in max_score (they only penalize).
    for af in fam.get("antisignature_files") or []:
        if _signal_matches_file(af, ev.files):
            score += weights["anti_file"]
            evidence.append(f"anti_file:{af}")
    for ar in fam.get("antisignature_rule_ids") or []:
        if ar.strip().lower() in ev.rule_ids:
            score += weights["anti_rule"]
            evidence.append(f"anti_rule:{ar}")

    # Clamp to [0, 1] after normalization; a sea of anti-signals must not
    # produce a negative confidence. SIGNAL_DENOMINATOR_K is a
    # regularization constant that stops a terse family (one signal) from
    # scoring 1.0 on a single match.
    confidence = max(0.0, score / (max_score + SIGNAL_DENOMINATOR_K))
    return FamilyVerdict(slug=fam["slug"], confidence=round(confidence, 3), evidence=evidence)


__all__ = [
    "DEFAULT_FLOOR",
    "DEFAULT_WEIGHTS",
    "ClassificationResult",
    "FamilyVerdict",
    "VictimEvidence",
    "classify",
]
