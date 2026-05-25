"""E2E: linker + graph boot concurrently against an empty data_dir over real NATS.

Replays the exact failure mode that surfaced during the M4 smoke
(commit e2aefbe close-out notes):
  - schema-init race produced `sqlite3.OperationalError: table system_user
    already exists` on the slower process,
  - audit hash-chain forked because two services wrote `service.stop`
    rows with the same `prev_hash`.

Both bugs are fixed at the storage layer; this test runs both processes
with no stagger and asserts no crash + chain intact end-to-end.

Gating:
- `EYENET_E2E=1` to opt in.
- Honors `EYENET_NATS_URL` for a pre-running server; otherwise spins
  `testcontainers.nats.NatsContainer`.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from eyenet.contracts.audit import GENESIS_PREV_HASH
from eyenet.storage.factory import get_repository

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("EYENET_E2E") != "1",
        reason="set EYENET_E2E=1 to enable real-NATS e2e tests",
    ),
]


@asynccontextmanager
async def _nats_url() -> AsyncIterator[str]:
    pre_running = os.environ.get("EYENET_NATS_URL")
    if pre_running:
        yield pre_running
        return

    from testcontainers.nats import NatsContainer  # type: ignore[import-untyped]

    with NatsContainer() as nats:
        yield f"nats://{nats.get_container_host_ip()}:{nats.get_exposed_port(4222)}"


def _spawn(cmd: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(  # noqa: S603 — known invocation, no shell
        cmd,
        env=env,
        stdout=log_path.open("wb"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


@pytest.mark.asyncio
async def test_linker_and_graph_concurrent_boot_chain_intact(tmp_path: Path) -> None:
    async with _nats_url() as url:
        data_dir = tmp_path / "data"
        env = {
            **os.environ,
            "EYENET_NATS_URL": url,
            "EYENET_DATA_DIR": str(data_dir),
        }

        # No stagger — both processes race on schema init AND audit appends.
        linker_log = tmp_path / "linker.log"
        graph_log = tmp_path / "graph.log"
        eyenet = [sys.executable, "-m", "eyenet.cli.main"]
        linker = _spawn([*eyenet, "linker"], env, linker_log)
        graph = _spawn([*eyenet, "graph"], env, graph_log)

        try:
            # Let both fully boot, subscribe, and emit `service.start`.
            await asyncio.sleep(5)

            # Neither should have crashed by now.
            assert linker.poll() is None, (
                f"linker exited early ({linker.returncode}). log:\n"
                f"{linker_log.read_text(errors='replace')}"
            )
            assert graph.poll() is None, (
                f"graph exited early ({graph.returncode}). log:\n"
                f"{graph_log.read_text(errors='replace')}"
            )
        finally:
            for p in (linker, graph):
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGTERM)
            for p in (linker, graph):
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait(timeout=5)

        # Walk the audit chain end-to-end. No forks allowed; both services
        # must have produced start + stop pairs.
        storage = get_repository(data_dir=data_dir)
        try:
            # `audit.all()` already orders by id asc (= commit order under
            # `BEGIN IMMEDIATE`). Re-sorting by `at` would scramble the
            # chain because `at` is emit time, not write-commit time.
            rows = await storage.all_audit()
        finally:
            await storage.close()

        assert len(rows) >= 4, f"expected ≥4 rows (linker+graph start/stop); got {len(rows)}"

        events = {(r.service, r.event) for r in rows}
        assert ("linker", "service.start") in events
        assert ("linker", "service.stop") in events
        assert ("graph", "service.start") in events
        assert ("graph", "service.stop") in events

        prev_hashes = [r.prev_hash for r in rows]
        assert len(set(prev_hashes)) == len(prev_hashes), (
            f"chain forked: duplicate prev_hash in {prev_hashes}"
        )

        expected = GENESIS_PREV_HASH
        for i, r in enumerate(rows):
            assert r.prev_hash == expected, (
                f"chain broken at row {i} ({r.service}/{r.event}): "
                f"prev={r.prev_hash[:8]} expected={expected[:8]}"
            )
            expected = r.self_hash
