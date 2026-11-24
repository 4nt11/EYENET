# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/rule-coverage-gaps - rule-authoring triage surface."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.rule_coverage import (
    RuleCoverageGapRow,
    RuleCoverageGapsResponse,
)
from eyenet.stealer.clickhouse import clickhouse_db, get_async_clickhouse_client

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/rule-coverage-gaps",
    operation_id="stealer_rule_coverage_gaps",
    response_model=RuleCoverageGapsResponse,
    status_code=200,
)
async def rule_coverage_gaps(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> RuleCoverageGapsResponse:
    db = clickhouse_db()
    try:
        client: Any = await get_async_clickhouse_client()
        res = await client.query(
            "SELECT "  # noqa: S608
            "  coalesce(nullIf(v.slug, ''), 'unknown') AS stealer_family, "
            "  count() AS total_victims, "
            "  countIf(er_fp.has_fp > 0) AS with_fp, "
            "  count() - countIf(er_fp.has_fp > 0) AS missing, "
            "  round(100.0 * (count() - countIf(er_fp.has_fp > 0)) / count(), 1) AS missing_pct "
            f"FROM {db}.victim_family_verdict AS v FINAL "  # nosec B608
            "LEFT JOIN ("
            "  SELECT archive_sha256, victim_folder, 1 AS has_fp "
            f"  FROM {db}.extracted_records_victim "  # nosec B608
            "  WHERE family = 'victim_fingerprint' "
            "  GROUP BY archive_sha256, victim_folder"
            ") AS er_fp USING (archive_sha256, victim_folder) "
            "GROUP BY stealer_family "
            "HAVING total_victims >= 5 "
            "ORDER BY missing DESC"
        )
    except Exception as exc:
        # Empty response if the corpus isn't initialised yet is nicer than 503.
        if "UNKNOWN_TABLE" in str(exc) or "Code: 60" in str(exc):
            return RuleCoverageGapsResponse(
                items=[], total_victims=0, total_missing=0, coverage_pct=0.0
            )
        raise HTTPException(status_code=503, detail=f"ch unavailable: {exc}") from exc
    items = [
        RuleCoverageGapRow(
            stealer_family=r[0],
            total_victims=int(r[1]),
            with_fingerprint=int(r[2]),
            missing_fingerprint=int(r[3]),
            missing_pct=float(r[4]),
        )
        for r in res.result_rows
    ]
    total_victims = sum(it.total_victims for it in items)
    total_missing = sum(it.missing_fingerprint for it in items)
    coverage_pct = (
        round(100.0 * (total_victims - total_missing) / total_victims, 1) if total_victims else 0.0
    )
    return RuleCoverageGapsResponse(
        items=items,
        total_victims=total_victims,
        total_missing=total_missing,
        coverage_pct=coverage_pct,
    )
