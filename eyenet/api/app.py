"""FastAPI app factory for EYENET v1 HTTP API.

`create_app()` is the canonical entry point. It mounts `v1_router` and wires
the two skeleton-tier exception handlers required for §7 (`application/problem+json`):

- `NotImplementedError` → 501 ProblemDetail. Every M9.0 stub raises this; the
  handler exists so Schemathesis and the §14.4 surface-diff test get a real
  HTTP response with the documented error envelope instead of FastAPI's
  default 500 plain-JSON.
- `RequestValidationError` → 422 ProblemDetail (populates `errors[]`).
  Replaces FastAPI's default `{"detail": [...]}` shape with our `ValidationError`
  rows so the wire shape conforms to the OpenAPI for free.

Auth, audit, tracing, rate-limit, request-id middleware land in M9.1+.
For now `request_id` is sourced from the `X-Request-Id` header or a fresh
ULID-shaped placeholder so ProblemDetail's required field is always populated.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from eyenet.api.v1 import v1_router
from eyenet.api.v1.schemas.errors import ProblemDetail, ValidationError

PROBLEM_JSON = "application/problem+json"


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or uuid4().hex


def _problem_response(problem: ProblemDetail, status_code: int) -> JSONResponse:
    return JSONResponse(
        content=problem.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
        media_type=PROBLEM_JSON,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="EYENET API",
        version="0.0.0",
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title="Not Implemented",
            status=501,
            detail=str(exc) or "Endpoint not yet implemented (M9.0 skeleton).",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 501)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            ValidationError(
                loc=[str(item) for item in err["loc"]],
                msg=err["msg"][:512],
                type=err["type"][:128],
            )
            for err in exc.errors()
        ]
        problem = ProblemDetail(
            type="about:blank",
            title="Validation Failed",
            status=422,
            detail="Request payload failed validation.",
            instance=request.url.path,
            request_id=_request_id(request),
            errors=errors,
        )
        return _problem_response(problem, 422)

    app.include_router(v1_router)
    return app


__all__ = ["create_app"]
