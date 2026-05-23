"""`NATSBus` — concrete `Bus` ABC implementation against `nats-py`.

PLAN §3: NATS core for v0; JetStream is enabled but durable-stream usage is
deferred until services need replay (Engine restart, Linker reprocessing).
This impl supports core pub/sub + queue groups + request/reply. JetStream
APIs are accessible via `client.jetstream()` from the underlying connection
when needed.

Drains the connection on `close()` so in-flight messages aren't lost on
operator-initiated shutdown.
"""

from __future__ import annotations

import contextlib

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg as NATSMsg
from nats.aio.subscription import Subscription as NATSSubscription

from eyenet.contracts.bus import Bus, Handler, Subscription


class _NATSSubWrapper(Subscription):
    def __init__(self, sub: NATSSubscription) -> None:
        self._sub = sub

    async def unsubscribe(self) -> None:
        with contextlib.suppress(Exception):
            await self._sub.unsubscribe()


class NATSBus(Bus):
    """Concrete `Bus` over `nats-py`."""

    def __init__(self, client: NATSClient) -> None:
        self._client = client

    @classmethod
    async def connect(cls, url: str = "nats://127.0.0.1:4222") -> NATSBus:
        client: NATSClient = await nats.connect(url)
        return cls(client)

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        await self._client.publish(subject, payload, headers=headers)

    async def subscribe(
        self,
        subject: str,
        handler: Handler,
        *,
        queue_group: str | None = None,
    ) -> Subscription:
        async def _adapter(msg: NATSMsg) -> None:
            hdrs = dict(msg.headers or {})
            await handler(msg.subject, msg.data, hdrs)

        sub = await self._client.subscribe(
            subject,
            queue=queue_group or "",
            cb=_adapter,
        )
        return _NATSSubWrapper(sub)

    async def request(
        self,
        subject: str,
        payload: bytes,
        *,
        timeout: float,  # noqa: ASYNC109
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        msg = await self._client.request(
            subject,
            payload,
            timeout=timeout,
            headers=headers,
        )
        return msg.data, dict(msg.headers or {})

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._client.drain()
        with contextlib.suppress(Exception):
            await self._client.close()


__all__ = ["NATSBus"]
