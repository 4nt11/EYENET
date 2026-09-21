# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI app factory for EYENET v1 HTTP API.

``create_app(*, storage, data_dir, publisher=None)`` is the canonical
entry point. It mounts ``v1_router`` and wires the exception handlers
required for §7 (``application/problem+json``):

- ``NotImplementedError`` → 501 ProblemDetail (skeleton routes).
- ``RequestValidationError`` → 422 ProblemDetail with per-field rows.
- ``AuthError`` → 401 ProblemDetail (no ``WWW-Authenticate`` header —
  bearer-token API clients don't key off it, and omitting it removes one
  deployment-info surface).
- ``ScopeForbidden`` → 403 ProblemDetail with the required scope in
  ``payload.required_scope``.

Storage, audit emitter, JWT verifying keys, and the auth cache live on
``app.state`` so dependencies in :mod:`eyenet.api.deps` can read them.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from eyenet.api.auth import AuthCache, load_mfa_key, load_pat_pepper, load_verifying_keys
from eyenet.api.deps import (
    AuthError,
    ConflictError,
    ResourceNotFound,
    ScopeForbidden,
    ServiceUnavailableError,
    UnprocessableError,
)
from eyenet.api.middleware import IdempotencyMiddleware, evidence_access_dispatch
from eyenet.api.v1 import v1_router
from eyenet.api.v1.schemas.errors import ProblemDetail, ValidationError
from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.storage.errors import SourceCanonicalUrlError, SourceDomainOverlapError
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter
from eyenet.telemetry.metrics import init_metrics, set_health

PROBLEM_JSON = "application/problem+json"


def _request_id(request: Request) -> str:
    # The evidence-access middleware (M9.F6) stashes one request id up front;
    # prefer it so error bodies and the audit row agree.
    stashed = getattr(request.state, "request_id", None)
    if isinstance(stashed, str):
        return stashed
    return request.headers.get("x-request-id") or uuid4().hex


def _problem_response(problem: ProblemDetail, status_code: int) -> JSONResponse:
    return JSONResponse(
        content=problem.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
        media_type=PROBLEM_JSON,
    )


def create_app(
    *,
    storage: BaseRepository,
    data_dir: Path,
    publisher: BusEnvelopePublisher | None = None,
    instance_id: str = "api-0",
) -> FastAPI:
    app = FastAPI(
        title="EYENET API",
        version="0.0.0",
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )

    bus_publisher = publisher or BusEnvelopePublisher(MemoryBus())
    app.state.storage = storage
    app.state.publisher = bus_publisher
    app.state.audit = AuditEmitter(
        bus_publisher,
        storage,
        service="api",
        instance_id=instance_id,
    )
    app.state.verifying_keys = load_verifying_keys(data_dir)
    app.state.mfa_key = load_mfa_key(data_dir)
    app.state.pat_pepper = load_pat_pepper(data_dir)
    app.state.data_dir = data_dir
    app.state.auth_cache = AuthCache.from_env()

    # M9.6 metrics (§11.7): sets the MeterProvider when a scrape/OTLP surface is
    # enabled via env; a no-op otherwise. Boot-time health gauges reflect "the
    # deployment came up". ponytail: dynamic re-check lands with the /healthz and
    # /readyz handlers (still M9.0 stubs); until then these are boot signals.
    init_metrics(service="eyenet-api", instance_id=instance_id)
    set_health("healthy", value=True)
    set_health("storage_open", value=True)
    set_health("bus_connected", value=True)
    for _component in ("storage", "bus", "jwt_keys"):
        set_health(f"ready:{_component}", value=True)

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

    @app.exception_handler(AuthError)
    async def _auth_error(request: Request, exc: AuthError) -> JSONResponse:  # noqa: ARG001 — FastAPI handler signature
        problem = ProblemDetail(
            type="about:blank",
            title="Unauthorized",
            status=401,
            detail="authentication failed",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 401)

    @app.exception_handler(ResourceNotFound)
    async def _resource_not_found(request: Request, exc: ResourceNotFound) -> JSONResponse:  # noqa: ARG001 — FastAPI handler signature; detail kept generic (no enumeration oracle)
        problem = ProblemDetail(
            type="about:blank",
            title="Not Found",
            status=404,
            detail="resource not found",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 404)

    @app.exception_handler(ScopeForbidden)
    async def _scope_forbidden(request: Request, exc: ScopeForbidden) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title="Forbidden",
            status=403,
            detail=f"missing required scope: {exc.scope}",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 403)

    @app.exception_handler(ConflictError)
    async def _conflict(request: Request, exc: ConflictError) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title="Conflict",
            status=409,
            detail=exc.detail,
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 409)

    @app.exception_handler(ServiceUnavailableError)
    async def _service_unavailable(request: Request, exc: ServiceUnavailableError) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title="Service Unavailable",
            status=503,
            detail=exc.detail,
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 503)

    @app.exception_handler(UnprocessableError)
    async def _unprocessable(request: Request, exc: UnprocessableError) -> JSONResponse:
        problem = ProblemDetail(
            type="about:blank",
            title="Unprocessable Entity",
            status=422,
            detail=exc.detail,
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 422)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:  # noqa: ARG001 — handler signature; DB message withheld (no oracle / no internal leak)
        # A unique/FK violation surfaced from a create (e.g. a collector reusing
        # a leased identity or a duplicate instance_name). 409; the raw DB error
        # is intentionally not echoed.
        problem = ProblemDetail(
            type="about:blank",
            title="Conflict",
            status=409,
            detail="resource conflicts with an existing row (unique or foreign-key constraint)",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 409)

    @app.exception_handler(SourceDomainOverlapError)
    async def _source_domain_overlap(
        request: Request,
        exc: SourceDomainOverlapError,
    ) -> JSONResponse:
        # §4.13 — a SourceDomain whose pattern can match a hostname already
        # owned by another non-removed row. 409; the conflicting id + kind go
        # in the detail (ProblemDetail forbids extra fields).
        problem = ProblemDetail(
            type="about:blank",
            title="Conflict",
            status=409,
            detail=(
                f"source_domain overlaps existing {exc.conflict_kind} row "
                f"(conflicting_domain_id={exc.conflicting_id})"
            ),
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 409)

    @app.exception_handler(SourceCanonicalUrlError)
    async def _source_canonical_url(
        request: Request,
        exc: SourceCanonicalUrlError,
    ) -> JSONResponse:
        # §4.13 — canonical_url must agree with the primary SourceDomain. The
        # stable reason tag (invalid_url / no_primary_domain / host_not_owned)
        # is part of the contract; surface it in the detail. 422.
        problem = ProblemDetail(
            type="about:blank",
            title="Validation Failed",
            status=422,
            detail=f"canonical_url rejected: {exc.reason}",
            instance=request.url.path,
            request_id=_request_id(request),
        )
        return _problem_response(problem, 422)

    # Evidence-access audit (§5.5): every successful read emits a durable
    # audit row before its body is served; audit-append failure → 503.
    # `app.middleware("http")` wraps it as a BaseHTTPMiddleware internally —
    # no direct starlette import needed.
    app.middleware("http")(evidence_access_dispatch)

    # Idempotency-Key replay guard (M9.G1, §6/§10.3) for POST /v1/* writes.
    # Pure ASGI so it can read the request body and capture the response.
    # Guards only writes (POST) with the header; reads flow through untouched.
    app.add_middleware(IdempotencyMiddleware)

    app.include_router(v1_router)
    return app


__all__ = ["create_app"]
