# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-family precision + recall against operator overrides.

Overrides form the labeled ground-truth set. For each stealer family F:

  TP_F: override says F, classifier said F
  FP_F: classifier said F, override says something else
  FN_F: override says F, classifier said something else (or no verdict)

The dashboard surfaces TP/FP/FN + derived precision/recall per family so
the rule author can see at a glance which families are over- or under-
claiming the corpus under the current signal set.

Verdicts live in ClickHouse (victim_family_verdict), overrides live in
Postgres (stealer_family_override). Both tables are small enough (~1k
rows each) to pull in full and join in Python; a push-down join across
stores would be complexity we do not need."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from eyenet.stealer.clickhouse import clickhouse_db, get_async_clickhouse_client
from eyenet.stealer.query import StealerCorpusUninitializedError, _is_unknown_table

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository


@dataclass(frozen=True, slots=True)
class FamilyMetric:
    slug: str
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    override_count: int  # how many overrides mention this slug (the ground-truth support)


async def family_metrics(storage: BaseRepository) -> list[FamilyMetric]:
    """Compute per-family metrics. Returns an empty list when the verdict
    table is not provisioned yet or when there are no overrides to label
    against."""
    # Pull every override from PG as a (sha, victim) -> slug map.
    overrides = await storage.list_stealer_family_overrides()
    if not overrides:
        return []
    override_by_key: dict[tuple[str, str], str] = {
        (o.archive_sha256, o.victim_folder): o.slug for o in overrides
    }

    # Pull every verdict from CH for the same keyset. One scan, bounded
    # by the override count.
    client = await get_async_clickhouse_client()
    db = clickhouse_db()
    try:
        result = await client.query(
            "SELECT archive_sha256, victim_folder, slug "  # noqa: S608  # nosec B608
            f"FROM {db}.victim_family_verdict FINAL"
        )
    except Exception as exc:
        if _is_unknown_table(exc):
            raise StealerCorpusUninitializedError(
                "stealer.victim_family_verdict table does not exist yet"
            ) from exc
        raise
    verdict_by_key: dict[tuple[str, str], str] = {}
    for sha, vf, slug in result.result_rows:
        verdict_by_key[(str(sha), str(vf))] = str(slug or "")

    # Score per family.
    tp: dict[str, int] = {}
    fp: dict[str, int] = {}
    fn: dict[str, int] = {}
    override_count: dict[str, int] = {}
    seen_families: set[str] = set()
    for key, override_slug in override_by_key.items():
        verdict_slug = verdict_by_key.get(key, "")
        seen_families.add(override_slug)
        if verdict_slug:
            seen_families.add(verdict_slug)
        override_count[override_slug] = override_count.get(override_slug, 0) + 1
        if verdict_slug == override_slug:
            tp[override_slug] = tp.get(override_slug, 0) + 1
        else:
            fn[override_slug] = fn.get(override_slug, 0) + 1
            if verdict_slug:
                fp[verdict_slug] = fp.get(verdict_slug, 0) + 1

    out: list[FamilyMetric] = []
    for slug in sorted(seen_families):
        tp_f = tp.get(slug, 0)
        fp_f = fp.get(slug, 0)
        fn_f = fn.get(slug, 0)
        precision = tp_f / (tp_f + fp_f) if (tp_f + fp_f) else 0.0
        recall = tp_f / (tp_f + fn_f) if (tp_f + fn_f) else 0.0
        out.append(
            FamilyMetric(
                slug=slug,
                tp=tp_f,
                fp=fp_f,
                fn=fn_f,
                precision=round(precision, 3),
                recall=round(recall, 3),
                override_count=override_count.get(slug, 0),
            )
        )
    out.sort(key=lambda m: (-m.override_count, m.slug))
    return out


__all__ = ["FamilyMetric", "family_metrics"]
