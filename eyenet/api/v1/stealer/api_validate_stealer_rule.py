# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/stealer/rules/validate: dry-run rule validation.

Runs the same shape + slug + canonical-field-name checks that a
Create/Update would run, WITHOUT writing anything to disk. Powers the
"Validate" button in the FE rule editor so an operator can catch errors
before they hit Save.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.stealer.rules.catalog.rw import validate_rule

router = APIRouter(tags=["stealer"])


class RuleValidateResponse(BaseModel):
    valid: bool
    error: str | None = None


@router.post(
    "/stealer/rules/validate",
    operation_id="stealer_rules_validate",
    response_model=RuleValidateResponse,
)
async def stealer_rules_validate(
    body: dict[str, Any],
    _current_user: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
) -> RuleValidateResponse:
    try:
        validate_rule(body)
    except ValueError as exc:
        return RuleValidateResponse(valid=False, error=str(exc))
    return RuleValidateResponse(valid=True, error=None)
