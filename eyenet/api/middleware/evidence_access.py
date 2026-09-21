# SPDX-License-Identifier: AGPL-3.0-or-later
"""Evidence-access audit middleware (M9.F6, API_PLAN §5.5).

Every *successful* read against the evidence surface emits a durable
``eyenet.audit.evidence_access`` row BEFORE the response body is served. If the
audit append fails, the body is withheld and the request gets 503 — no
evidence leaves the system without a non-repudiable access record
(operator-grade evidence, not privacy-minimized).

The middleware also establishes the per-request ``request_id`` (preferring an
inbound ``X-Request-ID``) on ``request.state`` so the error handlers and the
audit payload agree on one id.

Granularity is per-request (one row naming the resource family + path id), not
per-row: the middleware sees the response, not the rows. That satisfies the
non-repudiation invariant ("user U read path P at time T"); finer per-row
attribution would live in the handlers.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.schemas.errors import ProblemDetail
from eyenet.telemetry import metrics
from eyenet.telemetry.audit import AuditEmitter

_log = structlog.get_logger()

EVIDENCE_ACCESS_SUBJECT = "eyenet.audit.evidence_access"
_PROBLEM_JSON = "application/problem+json"
_V1_PREFIX = "/v1/"
# Responses at or above this status served no evidence body worth auditing.
_NON_SUCCESS_STATUS = 300

# `/v1/<family>` → audit subject_kind. The evidence-bearing read families.
_EVIDENCE_FAMILIES: dict[str, str] = {
    "actors": "actor",
    "personas": "persona",
    "linkages": "linkage",
    "graph": "graph",
    "audit": "audit",
}


def _evidence_kind(path: str) -> str | None:
    """Return the audit subject_kind for an evidence path, or None."""
    if not path.startswith(_V1_PREFIX):
        return None
    family = path[len(_V1_PREFIX) :].split("/", 1)[0]
    return _EVIDENCE_FAMILIES.get(family)


def _subject_id(request: Request) -> UUID | None:
    """The first UUID-valued path param (e.g. actor_id / linkage_id), if any."""
    for value in request.path_params.values():
        try:
            return UUID(str(value))
        except (ValueError, TypeError):
            continue
    return None


async def evidence_access_dispatch(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id

    start = time.perf_counter()
    response = await call_next(request)
    final = await _maybe_audit(request, response, request_id)
    _record_request(request, final, time.perf_counter() - start)
    return final


def _record_request(request: Request, response: Response, elapsed: float) -> None:
    # M9.6 request metrics (§11.7.2). Route TEMPLATE (not raw path) keeps
    # cardinality bounded; unmatched requests bucket under "unmatched".
    route = request.scope.get("route")
    route_tmpl = getattr(route, "path", "unmatched")
    attrs = {"method": request.method, "route": route_tmpl}
    metrics.requests_total.add(1, {**attrs, "status": str(response.status_code)})
    metrics.request_duration_seconds.record(elapsed, attrs)


async def _maybe_audit(request: Request, response: Response, request_id: str) -> Response:
    kind = _evidence_kind(request.url.path)
    if request.method != "GET" or kind is None or response.status_code >= _NON_SUCCESS_STATUS:
        return response

    audit: AuditEmitter = request.app.state.audit
    current_user = getattr(request.state, "current_user", None)
    system_user_id = current_user.user_id if isinstance(current_user, CurrentUser) else None
    try:
        await audit.emit(
            event=EVIDENCE_ACCESS_SUBJECT,
            subject_kind=kind,
            subject_id=_subject_id(request),
            system_user_id=system_user_id,
            payload={
                "path": request.url.path,
                "query": request.url.query,
                "request_id": request_id,
            },
        )
    except (SQLAlchemyError, OSError) as exc:
        # §5.5 hard gate: no evidence is served without a durable access
        # record. Withhold the body; surface 503.
        _log.warning(
            "evidence_access.audit_failed",
            path=request.url.path,
            error=str(exc),
        )
        problem = ProblemDetail(
            type="about:blank",
            title="Service Unavailable",
            status=503,
            detail="audit log unavailable; evidence withheld",
            instance=request.url.path,
            request_id=request_id,
        )
        return JSONResponse(
            content=problem.model_dump(mode="json", exclude_none=True),
            status_code=503,
            media_type=_PROBLEM_JSON,
        )
    return response


__all__ = ["EVIDENCE_ACCESS_SUBJECT", "evidence_access_dispatch"]
