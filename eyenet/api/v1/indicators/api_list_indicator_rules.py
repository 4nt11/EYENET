# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/indicators/rules — list the indicator-extraction ruleset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, get_storage
from eyenet.api.v1.schemas.indicators import IndicatorRuleOut
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["indicators"])


@router.get(
    "/indicators/rules",
    operation_id="indicator_rules_list",
    response_model=list[IndicatorRuleOut],
)
async def indicator_rules_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:collectors"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> list[IndicatorRuleOut]:
    rows = await storage.list_indicator_rules()
    return [IndicatorRuleOut.from_row(r) for r in rows]
