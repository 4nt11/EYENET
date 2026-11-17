# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/families: enumerate the family catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer_families import StealerFamilyListOut, StealerFamilyOut
from eyenet.stealer.families import load_families

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/families",
    operation_id="stealer_families_list",
    response_model=StealerFamilyListOut,
)
async def stealer_families_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerFamilyListOut:
    fams = load_families()
    return StealerFamilyListOut(
        families=[StealerFamilyOut.model_validate(f) for f in fams],
        total=len(fams),
    )
