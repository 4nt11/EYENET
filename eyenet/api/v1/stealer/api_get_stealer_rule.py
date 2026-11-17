# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/rules/{rule_id}: fetch one rule by slug."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound
from eyenet.api.v1.schemas.stealer_rules import StealerRuleOut
from eyenet.stealer.rules.catalog.rw import read_rule

router = APIRouter(tags=["stealer"])


@router.get(
    "/stealer/rules/{rule_id}",
    operation_id="stealer_rules_get",
    response_model=StealerRuleOut,
)
async def stealer_rules_get(
    rule_id: str,
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> StealerRuleOut:
    try:
        rule = read_rule(rule_id)
    except FileNotFoundError as exc:
        raise ResourceNotFound("stealer_rule") from exc
    except ValueError as exc:
        raise ResourceNotFound("stealer_rule") from exc
    return StealerRuleOut.model_validate(rule)
