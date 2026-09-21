# SPDX-License-Identifier: AGPL-3.0-or-later
"""IdempotencyMiddleware (M9.G1) — pure-ASGI replay guard.

Drives the middleware with hand-built ASGI scope/receive/send over a counting
inner app + a real in-memory repository as ``app.state.storage``.
"""

from __future__ import annotations

import pytest

from eyenet.api.middleware.idempotency import IdempotencyMiddleware
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


class _State:
    pass


class _App:
    def __init__(self, storage: BaseRepository) -> None:
        self.state = _State()
        self.state.storage = storage


class _Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def app(self, scope, receive, send) -> None:
        await receive()
        self.calls += 1
        payload = b'{"applied": false, "call": %d}' % self.calls
        await send(
            {
                "type": "http.response.start",
                "status": 202,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})


async def _post(
    mw: IdempotencyMiddleware,
    app: _App,
    key: str | None,
    body: bytes,
    path: str = "/v1/linkages/x/confirm",
):
    headers = [(b"idempotency-key", key.encode())] if key else []
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers, "app": app}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    await mw(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    resp_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, resp_body


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def test_replay_returns_stored_response_without_rerunning(storage: BaseRepository) -> None:
    counter = _Counter()
    mw = IdempotencyMiddleware(counter.app)
    app = _App(storage)
    body = b'{"reason": "dup"}'

    s1, b1 = await _post(mw, app, "K1", body)
    assert s1 == 202 and counter.calls == 1
    s2, b2 = await _post(mw, app, "K1", body)
    assert s2 == 202
    assert counter.calls == 1, "replay must NOT re-invoke the handler (no double bus emit)"
    assert b2 == b1, "replay must return the stored response verbatim"


async def test_same_key_different_body_conflicts(storage: BaseRepository) -> None:
    counter = _Counter()
    mw = IdempotencyMiddleware(counter.app)
    app = _App(storage)

    await _post(mw, app, "K2", b'{"reason": "a"}')
    status, _ = await _post(mw, app, "K2", b'{"reason": "DIFFERENT"}')
    assert status == 409
    assert counter.calls == 1


async def test_no_key_passes_through(storage: BaseRepository) -> None:
    counter = _Counter()
    mw = IdempotencyMiddleware(counter.app)
    app = _App(storage)

    s1, _ = await _post(mw, app, None, b'{"reason": "x"}')
    s2, _ = await _post(mw, app, None, b'{"reason": "x"}')
    assert s1 == 202 and s2 == 202
    assert counter.calls == 2, "no Idempotency-Key → every request runs"


async def test_non_2xx_is_not_cached(storage: BaseRepository) -> None:
    # An inner app that always 404s must not have its failure cached — a
    # corrected retry with the same key must reach the handler again.
    calls = {"n": 0}

    async def failing_app(scope, receive, send) -> None:
        await receive()
        calls["n"] += 1
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/problem+json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"status":404}', "more_body": False})

    mw = IdempotencyMiddleware(failing_app)
    app = _App(storage)
    await _post(mw, app, "K3", b"{}")
    await _post(mw, app, "K3", b"{}")
    assert calls["n"] == 2, "a non-2xx reservation must be dropped, not replayed"
