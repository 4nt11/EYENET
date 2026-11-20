# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator-driven dry-run classifier shift.

Takes a proposed in-memory family (signals, floor, weights, kind) and
scores it against the corpus alongside the current on-disk catalog.
Returns a before/after count delta plus a bounded list of per-victim
verdict shifts so the rule author can see the operational consequence
of a signal edit without touching the live verdict table.

Read-only: no writes to victim_family_verdict, no writes to the family
YAML catalog. A subsequent save is the operator editing the YAML via
the family editor (PUT /stealer/families/{slug}, write:stealer) and
re-running the classifier. See
development/STEALER_FAMILY_CLASSIFIER_DESIGN.md Phase 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eyenet.stealer.classifier import ClassificationResult, classify
from eyenet.stealer.classifier_io import collect_evidence
from eyenet.stealer.clickhouse import clickhouse_db, get_async_clickhouse_client
from eyenet.stealer.families.rw import list_family_slugs, read_family
from eyenet.stealer.query import StealerCorpusUninitializedError, _is_unknown_table

# Cap how many victims one dry-run touches. The classifier is cheap per
# victim (two small CH scans + a Python score loop), but at 1k+ victims
# the UX budget to wait on a form submission is small. The CLI dry-run
# covers the exhaustive case.
_DRYRUN_HARD_CAP = 500


@dataclass(frozen=True, slots=True)
class CountDelta:
    slug: str
    before: int
    after: int


@dataclass(frozen=True, slots=True)
class VictimShift:
    archive_sha256: str
    victim_folder: str
    before_slug: str
    before_confidence: float
    after_slug: str
    after_confidence: float


@dataclass(frozen=True, slots=True)
class DryRunResult:
    sampled: int
    counts: list[CountDelta]
    shifts: list[VictimShift]


async def dry_run(
    proposed: list[dict[str, Any]],
    *,
    limit: int = 200,
) -> DryRunResult:
    """Score the corpus twice: once with the on-disk catalog, once with
    the on-disk catalog shadowed by ``proposed`` (any family whose slug
    appears in ``proposed`` is replaced; the rest come from disk).

    Returns per-slug (before, after) counts across the sampled set plus
    a list of per-victim shifts: victims whose verdict slug changed.

    ``limit`` is clamped to ``_DRYRUN_HARD_CAP``; the sample is the
    first N (archive_sha256, victim_folder) pairs in lexicographic
    order, which is stable across runs so operators can iterate against
    the same sample while tweaking signals.
    """
    n = max(1, min(int(limit), _DRYRUN_HARD_CAP))
    before_catalog = _load_stealer_catalog()
    # Only kind=stealer proposals enter the overlay; a proposal that tries
    # to flip a family from content/tool/combolist to stealer is a catalog
    # design decision that must go through the family editor + persist
    # path, not a dry-run.
    overlay = {
        fam["slug"]: fam for fam in proposed if fam.get("slug") and fam.get("kind") == "stealer"
    }
    after_catalog = [overlay.get(fam["slug"], fam) for fam in before_catalog]
    # Families in `proposed` that are not in the catalog (brand-new slug)
    # join the after-catalog so the dry-run can preview a brand new
    # family's effect without saving it first.
    before_slugs = {fam["slug"] for fam in before_catalog}
    for fam in proposed:
        slug = fam.get("slug")
        if slug and slug not in before_slugs and fam.get("kind") == "stealer":
            after_catalog.append(fam)

    client = await get_async_clickhouse_client()
    db = clickhouse_db()
    try:
        # v1.3.5: dropped FINAL; see classifier_io.py.
        pair_rows = await client.query(
            "SELECT DISTINCT archive_sha256, victim_folder "  # noqa: S608  # nosec B608
            f"FROM {db}.file_audit "
            "WHERE victim_folder != '' "
            "ORDER BY archive_sha256, victim_folder "
            "LIMIT {n:UInt32}",
            parameters={"n": n},
        )
    except Exception as exc:
        if _is_unknown_table(exc):
            raise StealerCorpusUninitializedError(
                "stealer.file_audit table does not exist yet"
            ) from exc
        raise
    pairs = [(str(sha), str(vf)) for sha, vf in pair_rows.result_rows]

    before_counts: dict[str, int] = {}
    after_counts: dict[str, int] = {}
    shifts: list[VictimShift] = []
    for sha, vf in pairs:
        evidence = await collect_evidence(client, sha, vf)
        before = classify(evidence, catalog=before_catalog)
        after = classify(evidence, catalog=after_catalog)
        before_slug = _slug_of(before)
        after_slug = _slug_of(after)
        before_counts[before_slug] = before_counts.get(before_slug, 0) + 1
        after_counts[after_slug] = after_counts.get(after_slug, 0) + 1
        if before_slug != after_slug:
            shifts.append(
                VictimShift(
                    archive_sha256=sha,
                    victim_folder=vf,
                    before_slug=before_slug,
                    before_confidence=_conf_of(before),
                    after_slug=after_slug,
                    after_confidence=_conf_of(after),
                )
            )

    all_slugs = sorted(set(before_counts) | set(after_counts))
    counts = [
        CountDelta(
            slug=slug,
            before=before_counts.get(slug, 0),
            after=after_counts.get(slug, 0),
        )
        for slug in all_slugs
    ]
    # Sort: slugs that moved first (|after-before| DESC), then by after DESC.
    counts.sort(key=lambda c: (-abs(c.after - c.before), -c.after, c.slug))
    # Cap shifts list so a catastrophic "every victim moved" dry-run
    # cannot blow the response budget. Operator can re-run with a
    # tighter sample if they want to see more.
    shifts = shifts[:100]
    return DryRunResult(sampled=len(pairs), counts=counts, shifts=shifts)


def _slug_of(r: ClassificationResult) -> str:
    return r.verdict.slug if r.verdict else ""


def _conf_of(r: ClassificationResult) -> float:
    return r.verdict.confidence if r.verdict else 0.0


def _load_stealer_catalog() -> list[dict[str, Any]]:
    """Catalog filtered to kind=stealer; mirrors classifier._load_stealer_catalog
    but needs an independent copy so we can shadow families per dry-run
    without touching the classifier's own cached view."""
    out: list[dict[str, Any]] = []
    for slug in list_family_slugs():
        try:
            fam = read_family(slug)
        except (FileNotFoundError, ValueError):
            continue
        if fam.get("kind") == "stealer":
            out.append(fam)
    return out


__all__ = ["CountDelta", "DryRunResult", "VictimShift", "dry_run"]
