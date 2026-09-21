# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/openapi.json — the OpenAPI schema, gated behind ``read:graph``.

FastAPI's built-in schema route is served anonymously. For an operator-grade
forensic API that is a reconnaissance gift: the full endpoint/model surface,
free to anyone. Per §12.5 the schema must not be anonymous — so the built-in
route is disabled (``openapi_url=None`` in ``create_app``) and replaced by this
scope-gated one. The TypeScript client codegen (M9.I4) consumes it *with* a
``read:graph`` token, exactly as an operator would.

``include_in_schema=False`` keeps this route out of the very schema it serves,
so the hand-drafted-vs-generated surface diff stays clean.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from eyenet.api.deps import CurrentUser, RequireScope

router = APIRouter(tags=["meta"])


@router.get("/openapi.json", include_in_schema=False, operation_id="meta_openapi")
async def openapi_schema(
    _: Annotated[CurrentUser, Depends(RequireScope("read:graph"))],
    request: Request,
) -> JSONResponse:
    return JSONResponse(request.app.openapi())
