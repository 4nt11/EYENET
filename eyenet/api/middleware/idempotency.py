# SPDX-License-Identifier: AGPL-3.0-or-later
"""Idempotency-Key middleware (M9.G1, API_PLAN §6 invariant #6 / §10.3).

A **pure ASGI** middleware (not ``BaseHTTPMiddleware``) so it can both read the
request body — to hash it — and capture the response — to store and replay it —
without the body-consumption pitfalls of the streaming wrapper.

Guards every ``POST /v1/*`` that carries an ``Idempotency-Key`` header
(idempotency is opt-in by header presence). Flow:

1. Buffer the body; ``request_hash = sha256(method + path + body)``.
2. **Reserve** the key (reserve-first, storage layer): the winner runs the
   handler; a loser either replays the finalized response or gets a 409.
3. On a 2xx response, **finalize** the record (store status + body) so a replay
   returns it verbatim. On any non-2xx, **delete** the reservation — nothing
   durable or on the bus happened, so a corrected retry must not replay the
   failure (and an unauthenticated first attempt must not poison the key).

Replays return the stored response WITHOUT re-invoking the handler, so bus
events are never re-emitted (invariant #6).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from eyenet.api.v1.schemas.errors import ProblemDetail
from eyenet.telemetry import metrics

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

_V1_PREFIX = "/v1/"
_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 3600  # §15 resolution: 7 days
_JSON = "application/json"
_PROBLEM_JSON = "application/problem+json"
_HTTP_OK, _HTTP_MULTIPLE_CHOICES = 200, 300


@dataclass(slots=True)
class _Captured:
    status: int = 0
    body: bytes = b""


class IdempotencyMiddleware:
    """See module docstring."""

    def __init__(self, app: ASGIApp, *, ttl_seconds: int = _IDEMPOTENCY_TTL_SECONDS) -> None:
        self.app = app
        self.ttl_seconds = ttl_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        key = _header(scope, b"idempotency-key")
        if not path.startswith(_V1_PREFIX) or not key:
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        request_hash = hashlib.sha256(
            scope["method"].encode() + b" " + path.encode() + b"\n" + body
        ).hexdigest()
        storage = scope["app"].state.storage

        reserve = await storage.reserve_idempotency_record(
            key=key,
            request_hash=request_hash,
            system_user_id=None,  # auth runs downstream; the operator_action audit row carries who
            ttl_seconds=self.ttl_seconds,
        )
        if not reserve.won:
            await self._handle_contended(send, path, reserve.existing, request_hash)
            return

        captured = _Captured()
        try:
            await self.app(scope, _replay_receive(body), _capturing_send(send, captured))
        except BaseException:
            with contextlib.suppress(Exception):
                await storage.delete_idempotency_record(key)
            raise

        if _HTTP_OK <= captured.status < _HTTP_MULTIPLE_CHOICES:
            await storage.finalize_idempotency_record(
                key=key,
                response_status=captured.status,
                response_body=_decode_json(captured.body),
                bus_state="delivered",
            )
        else:
            await storage.delete_idempotency_record(key)

    async def _handle_contended(
        self, send: Send, path: str, existing: object, request_hash: str
    ) -> None:
        # `existing` is IdempotencyRecordRow | None (kept `object` to avoid a
        # runtime contracts import in the middleware).
        if existing is None:
            await _send_problem(send, 409, path, "idempotency reservation contended; retry")
        elif getattr(existing, "request_hash", None) != request_hash:
            await _send_problem(
                send, 409, path, "Idempotency-Key reused with a different request body"
            )
        elif not getattr(existing, "is_finalized", False):
            await _send_problem(
                send, 409, path, "a request with this Idempotency-Key is still in progress"
            )
        else:
            # Finalized record → replay the stored response without re-invoking
            # the handler (M9.6 SLI §11.7.2).
            metrics.idempotency_replays_total.add(1)
            await _send_json(
                send,
                getattr(existing, "response_status", 202),
                getattr(existing, "response_body", None) or {},
            )


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return str(bytes(v).decode("latin-1"))[:128]
    return None


async def _read_body(receive: Receive) -> bytes:
    body = b""
    more = True
    while more:
        message = await receive()
        body += message.get("body", b"")
        more = message.get("more_body", False)
    return body


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _capturing_send(send: Send, captured: _Captured) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            captured.status = message["status"]
        elif message["type"] == "http.response.body":
            captured.body += message.get("body", b"")
        await send(message)

    return wrapped


def _decode_json(body: bytes) -> dict[str, object]:
    if not body:
        return {}
    try:
        decoded = json.loads(body)
    except (ValueError, TypeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


async def _send_json(send: Send, status: int, payload: dict[str, object]) -> None:
    data = json.dumps(payload).encode()
    await _raw_send(send, status, data, _JSON)


async def _send_problem(send: Send, status: int, path: str, detail: str) -> None:
    problem = ProblemDetail(
        type="about:blank",
        title="Conflict",
        status=status,
        detail=detail,
        instance=path,
        request_id=uuid4().hex,
    )
    data = json.dumps(problem.model_dump(mode="json", exclude_none=True)).encode()
    await _raw_send(send, status, data, _PROBLEM_JSON)


async def _raw_send(send: Send, status: int, data: bytes, content_type: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(data)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": data, "more_body": False})


__all__ = ["IdempotencyMiddleware"]
