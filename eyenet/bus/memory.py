"""In-process `MemoryBus` for unit/integration tests.

PLAN §7.3: integration tests run over an in-memory bus. Implements the same
`Bus` ABC as `NATSBus` so service code is identical between modes.

Semantics:
- `subscribe(subject, handler, queue_group=None)` — subjects support `*`
  and `>` wildcards. With `queue_group` set, deliveries are load-balanced
  round-robin across members of the group; without it, every matching
  subscriber receives every matching message.
- `publish(subject, payload, headers=None)` — fan-out to all matching
  subscribers (or one per group). Handlers run as awaited tasks; failures
  in one handler do not block others.
- `request(subject, payload, timeout)` — picks the first matching responder
  on a unique inbox subject and waits.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from eyenet.contracts.bus import Bus, Handler, Subscription

from .subjects import is_valid_pattern, subject_matches


@dataclass
class _Sub:
    pattern: str
    handler: Handler
    queue_group: str | None
    sid: str = field(default_factory=lambda: uuid4().hex)
    cancelled: bool = False


class _MemorySubscription(Subscription):
    def __init__(self, bus: MemoryBus, sub: _Sub) -> None:
        self._bus = bus
        self._sub = sub

    async def unsubscribe(self) -> None:
        self._sub.cancelled = True
        self._bus._remove(self._sub)


class MemoryBus(Bus):
    """In-process bus. NOT thread-safe; designed for single-event-loop use."""

    def __init__(self) -> None:
        self._subs: list[_Sub] = []
        # Round-robin pointer per queue-group name.
        self._rr: dict[str, int] = {}
        self._closed = False

    # -- Bus ABC ------------------------------------------------------------

    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        if self._closed:
            raise RuntimeError("MemoryBus is closed")
        hdrs = dict(headers or {})
        await self._fanout(subject, payload, hdrs)

    async def subscribe(
        self,
        subject: str,
        handler: Handler,
        *,
        queue_group: str | None = None,
    ) -> Subscription:
        if not is_valid_pattern(subject):
            raise ValueError(f"invalid subject pattern: {subject!r}")
        sub = _Sub(pattern=subject, handler=handler, queue_group=queue_group)
        self._subs.append(sub)
        return _MemorySubscription(self, sub)

    async def request(
        self,
        subject: str,
        payload: bytes,
        *,
        timeout: float,  # noqa: ASYNC109
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        inbox = f"_INBOX.{uuid4().hex}"
        fut: asyncio.Future[tuple[bytes, dict[str, str]]] = (
            asyncio.get_running_loop().create_future()
        )

        async def _on_reply(_subject: str, body: bytes, hdrs: dict[str, str]) -> None:
            if not fut.done():
                fut.set_result((body, hdrs))

        sub = await self.subscribe(inbox, _on_reply)
        try:
            reply_hdrs = dict(headers or {})
            reply_hdrs["__reply_to__"] = inbox
            await self.publish(subject, payload, headers=reply_hdrs)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            await sub.unsubscribe()

    async def close(self) -> None:
        self._closed = True
        self._subs.clear()
        self._rr.clear()

    # -- internals ---------------------------------------------------------

    def _remove(self, sub: _Sub) -> None:
        with contextlib.suppress(ValueError):
            self._subs.remove(sub)

    async def _fanout(
        self,
        subject: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> None:
        # Group matching subscribers by queue-group. None => broadcast.
        broadcast: list[_Sub] = []
        groups: dict[str, list[_Sub]] = {}
        for sub in list(self._subs):
            if sub.cancelled or not subject_matches(sub.pattern, subject):
                continue
            if sub.queue_group is None:
                broadcast.append(sub)
            else:
                groups.setdefault(sub.queue_group, []).append(sub)

        targets: list[_Sub] = list(broadcast)
        for group_name, members in groups.items():
            chosen = self._pick_round_robin(group_name, members)
            if chosen is not None:
                targets.append(chosen)

        # Dispatch concurrently. A failing handler must not block siblings.
        await asyncio.gather(
            *(self._invoke(sub.handler, subject, payload, headers) for sub in targets),
            return_exceptions=True,
        )

    def _pick_round_robin(self, group_name: str, members: list[_Sub]) -> _Sub | None:
        if not members:
            return None
        # Sort by sid for stable ordering across membership churn.
        ordered = sorted(members, key=lambda m: m.sid)
        idx = self._rr.get(group_name, 0) % len(ordered)
        self._rr[group_name] = idx + 1
        return ordered[idx]

    @staticmethod
    async def _invoke(
        handler: Callable[..., Awaitable[None]],
        subject: str,
        payload: bytes,
        headers: dict[str, str],
    ) -> None:
        await handler(subject, payload, headers)


__all__ = ["MemoryBus"]
