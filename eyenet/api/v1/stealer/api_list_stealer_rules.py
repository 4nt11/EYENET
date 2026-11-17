# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/rules: enumerate the active stealer rule catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.stealer_rules import StealerRuleListOut, StealerRuleOut
from eyenet.stealer.rules.catalog import load_catalog

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/rules",
    operation_id="stealer_rules_list",
    response_model=StealerRuleListOut,
)
async def stealer_rules_list(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerRuleListOut:
    rules = load_catalog()
    return StealerRuleListOut(
        rules=[StealerRuleOut.model_validate(r) for r in rules],
        total=len(rules),
    )
