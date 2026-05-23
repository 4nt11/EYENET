"""`Bus` ABC — abstract factory for the message bus (PLAN §3).

NATS is the v0 implementation; the interface exists so we can swap if NATS
fails us. `MemoryBus` lives in `tests/` for unit tests.

Subjects are documented in PLAN §3 (and asserted by `test_subject_taxonomy`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

# Handler signature: receives the (subject, payload_bytes, headers) tuple.
# Concrete implementations of `subscribe` adapt this from their native
# message type.
Handler = Callable[[str, bytes, dict[str, str]], Awaitable[None]]


class Subscription(ABC):
    """Handle on an active subscription. `unsubscribe` is idempotent."""

    @abstractmethod
    async def unsubscribe(self) -> None:
        """Stop delivering messages and release resources."""


class Bus(ABC):
    """Abstract bus. All EYENET services interact with the bus only here."""

    @abstractmethod
    async def publish(
        self,
        subject: str,
        payload: bytes,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish raw bytes on `subject` with optional W3C trace headers."""

    @abstractmethod
    async def subscribe(
        self,
        subject: str,
        handler: Handler,
        *,
        queue_group: str | None = None,
    ) -> Subscription:
        """Subscribe to `subject` (NATS-style wildcards allowed).

        When `queue_group` is set, deliveries are load-balanced across
        members of that group — the foundation for the stateless sensor fleet
        (PLAN §2.2).
        """

    @abstractmethod
    async def request(
        self,
        subject: str,
        payload: bytes,
        *,
        timeout: float,  # noqa: ASYNC109 — request/reply timeout is a transport contract
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """Request/reply over `subject`. Returns `(payload, headers)`."""

    @abstractmethod
    async def close(self) -> None:
        """Drain and close the underlying transport."""

    # Async-context-manager sugar so services can `async with bus:`.

    async def __aenter__(self) -> Bus:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


__all__ = ["Bus", "Handler", "Subscription"]
