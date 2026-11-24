# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse side of the per-victim family classifier.

:func:`collect_evidence` reads the files + paths + rule_ids + build_tag
for one (archive, victim) out of file_audit + extracted_records.
:func:`write_verdict` persists the verdict into the
``victim_family_verdict`` ReplacingMergeTree so the drawer detail endpoint
can read it by exact key.

Split from :mod:`eyenet.stealer.classifier` so the pure scorer stays
unit-testable without a ClickHouse dependency.
"""

from __future__ import annotations

from typing import Any

from eyenet.stealer.classifier import ClassificationResult, VictimEvidence
from eyenet.stealer.clickhouse import clickhouse_db

# Canonical build-tag field names, in priority order: build_tag, build_version,
# build.version (first non-empty wins). Extracted inline in the evidence queries
# below; see stealerCanonicalFields.js on the FE for the parallel mapping.


def collect_evidence_sync(client: Any, archive_sha256: str, victim_folder: str) -> VictimEvidence:
    """Synchronous collector. Runs two cheap aggregations against CH and
    returns the victim's evidence set. Sync because the reindex CLI uses
    a sync CH client to stay in the same thread as the gotractor daemon
    stream; the async service calls :func:`collect_evidence` instead."""
    db = clickhouse_db()
    # v1.3.5: dropped FINAL. DISTINCT on the projected (filename, rel_path)
    # tuple already dedupes the exact rows FINAL would collapse, since those
    # columns are stable across reindex generations for the same (archive,
    # victim, file_path, fields-hash) identity. Live diff on prod confirmed
    # zero symmetric difference between the two forms. 5x speedup on hot
    # cache; removes the memory-241 trigger during reclassify.
    files_rows = client.query(
        f"SELECT DISTINCT fa.filename, fa.rel_path "  # noqa: S608  # nosec B608
        f"FROM {db}.file_audit AS fa "
        "WHERE fa.archive_sha256 = %(sha)s "
        "  AND fa.victim_folder = %(vf)s "
        "  AND fa.heuristic_kind NOT IN ('empty','binary') "
        "  AND fa.filename != ''",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    ).result_rows
    files: list[str] = []
    paths: list[str] = []
    for fn, rel in files_rows:
        if fn:
            files.append(str(fn))
        if rel:
            paths.append(str(rel))

    # Aggregate, do NOT `SELECT DISTINCT rule_id, fields`: the latter pulls the
    # full fields Map for every row and hashes serialized maps to dedup, which on
    # a 2.5M-row combolist victim peaked ~562 MiB / 12.5s. groupUniqArray(rule_id)
    # IS the distinct rule set; max() per build key returns the one value (verified
    # corpus-wide: no victim carries >1 value for a key, and the keys are mutually
    # exclusive, so this matches the old first-non-empty-per-row result exactly).
    # ~10x faster, ~5.4x less memory, identical output. Build-key priority
    # (build_tag, build_version, build.version) is preserved by the max() order.
    rows = client.query(
        "SELECT groupUniqArray(er.rule_id) AS rule_ids, "  # noqa: S608  # nosec B608
        "       max(er.fields['build_tag']) AS bt, "
        "       max(er.fields['build_version']) AS bv, "
        "       max(er.fields['build.version']) AS bd "
        f"FROM {db}.extracted_records_victim AS er "
        "WHERE er.archive_sha256 = %(sha)s "
        "  AND er.victim_folder = %(vf)s",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    ).result_rows
    rule_ids: set[str] = set()
    build_tag = ""
    if rows:
        raw_rule_ids, bt, bv, bd = rows[0]
        rule_ids = {str(r).strip().lower() for r in (raw_rule_ids or []) if r}
        build_tag = next((str(v) for v in (bt, bv, bd) if v), "")

    return VictimEvidence(
        files=frozenset(f.lower() for f in files),
        paths=frozenset(p.lower() for p in paths),
        rule_ids=frozenset(rule_ids),
        build_tag=build_tag,
    )


async def collect_evidence(client: Any, archive_sha256: str, victim_folder: str) -> VictimEvidence:
    """Async equivalent used by the HTTP API path."""
    db = clickhouse_db()
    files_rows = await client.query(
        f"SELECT DISTINCT fa.filename, fa.rel_path "  # noqa: S608  # nosec B608
        f"FROM {db}.file_audit AS fa "
        "WHERE fa.archive_sha256 = {sha:FixedString(64)} "
        "  AND fa.victim_folder = {vf:String} "
        "  AND fa.heuristic_kind NOT IN ('empty','binary') "
        "  AND fa.filename != ''",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    )
    files: list[str] = []
    paths: list[str] = []
    for fn, rel in files_rows.result_rows:
        if fn:
            files.append(str(fn))
        if rel:
            paths.append(str(rel))

    # Aggregate rather than DISTINCT-over-maps (see collect_evidence_sync for the
    # why + the corpus-wide equivalence proof). Same output, far less memory.
    result = await client.query(
        "SELECT groupUniqArray(er.rule_id) AS rule_ids, "  # noqa: S608  # nosec B608
        "       max(er.fields['build_tag']) AS bt, "
        "       max(er.fields['build_version']) AS bv, "
        "       max(er.fields['build.version']) AS bd "
        f"FROM {db}.extracted_records_victim AS er "
        "WHERE er.archive_sha256 = {sha:FixedString(64)} "
        "  AND er.victim_folder = {vf:String}",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    )
    rule_ids: set[str] = set()
    build_tag = ""
    if result.result_rows:
        raw_rule_ids, bt, bv, bd = result.result_rows[0]
        rule_ids = {str(r).strip().lower() for r in (raw_rule_ids or []) if r}
        build_tag = next((str(v) for v in (bt, bv, bd) if v), "")

    return VictimEvidence(
        files=frozenset(f.lower() for f in files),
        paths=frozenset(p.lower() for p in paths),
        rule_ids=frozenset(rule_ids),
        build_tag=build_tag,
    )


def write_verdict_sync(
    client: Any,
    archive_sha256: str,
    victim_folder: str,
    result: ClassificationResult,
) -> None:
    """Persist the verdict into the ReplacingMergeTree. Idempotent per
    key; a re-run overwrites the stale row on merge."""
    db = clickhouse_db()
    verdict = result.verdict
    slug = verdict.slug if verdict else ""
    confidence = float(verdict.confidence) if verdict else 0.0
    evidence = list(verdict.evidence) if verdict else []
    runners_up = [(ru.slug, float(ru.confidence)) for ru in result.runners_up]
    client.insert(
        f"{db}.victim_family_verdict",
        [[archive_sha256, victim_folder, slug, confidence, evidence, runners_up]],
        column_names=[
            "archive_sha256",
            "victim_folder",
            "slug",
            "confidence",
            "evidence",
            "runners_up",
        ],
    )


__all__ = [
    "collect_evidence",
    "collect_evidence_sync",
    "write_verdict_sync",
]
