"""Async runner for `ServiceBase` subclasses.

Boot order (M1, PLAN §10):
  1. Init telemetry for (service.name, instance_id).
  2. Emit `service.start` audit + syslog.
  3. Call `on_subscribe()` to attach handlers / claim resources.
  4. Emit `service.ready` syslog.
  5. Install SIGTERM/SIGINT handlers that set `service.stop_event`.
  6. Loop: await stop event, with optional `tick()` cadence.
  7. Drain bus, close storage, emit `service.stop` audit.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from eyenet.contracts.enums import SystemLogLevel
from eyenet.telemetry import init_telemetry

from .base import ServiceBase


async def run_service(service: ServiceBase, *, tick_interval: float = 0.0) -> None:
    """Run a service to completion. Returns when stop_event is set."""

    init_telemetry(service=service.name, instance_id=service.instance_id)

    await service.audit.emit(
        event="service.start",
        subject_kind="service",
        payload={"name": service.name, "instance_id": service.instance_id},
    )
    await service.syslog(
        level=SystemLogLevel.LIFECYCLE,
        event="service.start",
        message=f"{service.name}/{service.instance_id} starting",
    )

    await service.on_subscribe()

    await service.syslog(
        level=SystemLogLevel.LIFECYCLE,
        event="service.ready",
        message=f"{service.name}/{service.instance_id} ready",
    )

    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, service)

    try:
        if tick_interval > 0:
            while not service.stop_event.is_set():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(service.stop_event.wait(), timeout=tick_interval)
                if not service.stop_event.is_set():
                    await service.tick()
        else:
            await service.stop_event.wait()
    finally:
        await service.audit.emit(
            event="service.stop",
            subject_kind="service",
            payload={"name": service.name, "instance_id": service.instance_id},
        )
        await service.syslog(
            level=SystemLogLevel.LIFECYCLE,
            event="service.shutdown",
            message=f"{service.name}/{service.instance_id} stopping",
        )
        # Bus close is the caller's responsibility: services running in the
        # same process MUST share a bus, and the first service to exit can't
        # close it on its siblings.


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    service: ServiceBase,
) -> None:
    def _handler() -> None:
        # Schedule shutdown on the loop. Idempotent.
        loop.create_task(service.shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, _handler)


__all__ = ["run_service"]
