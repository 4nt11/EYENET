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

# Canonical field names that carry the build tag. First match wins; see
# stealerCanonicalFields.js on the FE for the parallel mapping.
_BUILD_TAG_ALIASES: tuple[str, ...] = (
    "build_tag",
    "build_version",
    "build.version",
)


def collect_evidence_sync(client: Any, archive_sha256: str, victim_folder: str) -> VictimEvidence:
    """Synchronous collector. Runs two cheap aggregations against CH and
    returns the victim's evidence set. Sync because the reindex CLI uses
    a sync CH client to stay in the same thread as the gotractor daemon
    stream; the async service calls :func:`collect_evidence` instead."""
    db = clickhouse_db()
    files_rows = client.query(
        f"SELECT DISTINCT fa.filename, fa.rel_path "  # noqa: S608  # nosec B608
        f"FROM {db}.file_audit AS fa FINAL "
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

    rec_rows = client.query(
        "SELECT DISTINCT er.rule_id, er.fields "  # noqa: S608  # nosec B608
        f"FROM {db}.extracted_records AS er FINAL "
        "WHERE er.archive_sha256 = %(sha)s "
        "  AND er.victim_folder = %(vf)s",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    ).result_rows
    rule_ids: set[str] = set()
    build_tag = ""
    for rule_id, fields in rec_rows:
        if rule_id:
            rule_ids.add(str(rule_id).strip().lower())
        if build_tag:
            continue
        if isinstance(fields, dict):
            for k in _BUILD_TAG_ALIASES:
                v = fields.get(k)
                if v:
                    build_tag = str(v)
                    break

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
        f"FROM {db}.file_audit AS fa FINAL "
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

    rec_rows = await client.query(
        "SELECT DISTINCT er.rule_id, er.fields "  # noqa: S608  # nosec B608
        f"FROM {db}.extracted_records AS er FINAL "
        "WHERE er.archive_sha256 = {sha:FixedString(64)} "
        "  AND er.victim_folder = {vf:String}",
        parameters={"sha": archive_sha256, "vf": victim_folder},
    )
    rule_ids: set[str] = set()
    build_tag = ""
    for rule_id, fields in rec_rows.result_rows:
        if rule_id:
            rule_ids.add(str(rule_id).strip().lower())
        if build_tag:
            continue
        if isinstance(fields, dict):
            for k in _BUILD_TAG_ALIASES:
                v = fields.get(k)
                if v:
                    build_tag = str(v)
                    break

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
