# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/families/{slug}: fetch one family."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound
from eyenet.api.v1.schemas.stealer_families import StealerFamilyOut
from eyenet.stealer.families.rw import read_family

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/families/{slug}",
    operation_id="stealer_families_get",
    response_model=StealerFamilyOut,
)
async def stealer_families_get(
    slug: str,
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerFamilyOut:
    try:
        fam = read_family(slug)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_family") from exc
    except ValueError as exc:
        raise ResourceNotFound("stealer_family") from exc
    return StealerFamilyOut.model_validate(fam)
