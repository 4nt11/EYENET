# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/artifacts/{archive_sha256}/{victim_folder} (read:stealer).

Backs the drawer header + Overview tab. Returns the full profile fields
plus the resolved MITRE ATT&CK technique list derived from the artifact's
fired rule_ids.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer import (
    StealerArtifactDetail,
    StealerArtifactStatTiles,
    StealerTechnique,
)
from eyenet.api.v1.stealer._artifacts import reader
from eyenet.stealer.query import StealerCorpusUninitializedError
from eyenet.stealer.ttps import resolve_techniques

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/artifacts/{archive_sha256}/{victim_folder:path}",
    operation_id="stealer_get_artifact",
    response_model=StealerArtifactDetail,
    status_code=200,
)
async def stealer_get_artifact(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    archive_sha256: Annotated[str, Path(min_length=64, max_length=64)],
    victim_folder: Annotated[str, Path(min_length=1, max_length=512)],
) -> StealerArtifactDetail:
    try:
        row = await reader.detail(archive_sha256, victim_folder)
    except StealerCorpusUninitializedError as exc:
        raise HTTPException(503, "stealer corpus not initialized yet") from exc
    if row is None:
        raise HTTPException(404, "artifact not found")

    techs_raw = resolve_techniques(row.fired_rule_ids)
    techniques = [
        StealerTechnique(
            technique_id=str(t["technique_id"]),
            name=str(t["name"]),
            tactic=str(t["tactic"]),
            tactic_id=str(t["tactic_id"]),
            url=str(t["url"]),
            fired_from_rules=list(t["fired_from_rules"]),  # type: ignore[call-overload]
        )
        for t in techs_raw
    ]

    # Stat tiles: a condensed view for the top strip.
    # related stays 0 until cross-artifact linkage (shared HWID/MachineGuid)
    # ships; domain_hits now reflects the monitored_domains join.
    tiles = StealerArtifactStatTiles(
        credentials=row.creds_count,
        domain_hits=row.monitored_domain_hits,
        cookies=row.cookies_count,
        country=row.country,
        related=0,
        coverage_pct=row.coverage_pct,
        coverage_total=row.coverage_total_files,
        coverage_parsed=row.coverage_parsed_files,
    )

    return StealerArtifactDetail(
        archive_sha256=row.archive_sha256,
        victim_folder=row.victim_folder,
        source=row.source,
        country=row.country,
        egress_ip=row.egress_ip,
        user_name=row.user_name,
        computer_name=row.computer_name,
        os_version=row.os_version,
        traffic_affid=row.traffic_affid,
        build_version=row.build_version,
        payload_md5=row.payload_md5,
        work_dir=row.work_dir,
        stat_tiles=tiles,
        creds_count=row.creds_count,
        cookies_count=row.cookies_count,
        autofills_count=row.autofills_count,
        history_count=row.history_count,
        downloads_count=row.downloads_count,
        processes_count=row.processes_count,
        software_count=row.software_count,
        discord_tokens_count=row.discord_tokens_count,
        steam_tokens_count=row.steam_tokens_count,
        google_refresh_count=row.google_refresh_count,
        localstorage_jwt_count=row.localstorage_jwt_count,
        wallet_vaults_count=row.wallet_vaults_count,
        has_corporate_marker=row.has_corporate_marker,
        has_webmail_leak=row.has_webmail_leak,
        has_wallet=row.has_wallet,
        has_crypter_banner=row.has_crypter_banner,
        webmail_identity=row.webmail_identity,
        first_corporate_marker=row.first_corporate_marker,
        first_wallet_family=row.first_wallet_family,
        techniques=techniques,
    )
