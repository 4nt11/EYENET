"""E2E: real NATS via testcontainers, two services boot, panic kills clean.

Skipped unless `EYENET_E2E=1` is set in the environment, because spinning a
container on every CI run for a smoke test is overkill.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from eyenet.bus import NATSBus
from eyenet.engine.skeleton import EngineSkeleton
from eyenet.linker.linker import Linker
from eyenet.service import run_service
from eyenet.storage import SQLiteStorage

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("EYENET_E2E") != "1",
        reason="set EYENET_E2E=1 to enable testcontainers-backed e2e tests",
    ),
]


@pytest.mark.asyncio
async def test_two_services_against_real_nats(tmp_path: Path) -> None:
    from testcontainers.nats import NatsContainer  # type: ignore[import-untyped]

    with NatsContainer() as nats:
        url = f"nats://{nats.get_container_host_ip()}:{nats.get_exposed_port(4222)}"
        bus_a = await NATSBus.connect(url)
        bus_b = await NATSBus.connect(url)
        storage = SQLiteStorage(tmp_path / "data")
        try:
            engine = EngineSkeleton(bus=bus_a, storage=storage)
            linker = Linker(bus=bus_b, storage=storage)

            engine_task = asyncio.create_task(run_service(engine))
            linker_task = asyncio.create_task(run_service(linker))

            await asyncio.sleep(0.5)
            await engine.shutdown()
            await linker.shutdown()
            await asyncio.gather(engine_task, linker_task)

            rows = await storage.audit.all()
            services = {r.service for r in rows}
            assert {"engine", "linker"} <= services
        finally:
            await bus_a.close()
            await bus_b.close()
            await storage.close()
