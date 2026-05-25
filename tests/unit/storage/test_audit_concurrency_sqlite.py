"""Cross-process audit appends must produce a linear hash chain.

Without `BEGIN IMMEDIATE` in `SQLiteAuditStore.append()`, two `eyenet`
processes can both read the same `prev_hash` before either commits and
fork the chain. The smoke that produced the bug had two `service.stop`
rows whose `prev_hash` both pointed at the same `service.start`.

This test pre-creates the schema (so the init race is decoupled — see
`test_init_concurrency.py`) and then races 4 processes writing 25 rows
each, asserting the resulting 100-row chain walks linearly.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from eyenet.contracts.audit import GENESIS_PREV_HASH


def _append_worker(args: tuple[str, str, int]) -> str:
    data_dir, service, n = args
    # Open a fresh storage in the subprocess. The init lock makes this safe
    # even though the parent already opened the data_dir.
    import os

    from eyenet.storage.factory import get_repository

    os.environ["EYENET_STORAGE_TYPE"] = "sqlite"
    storage = get_repository(data_dir=Path(data_dir))

    async def run() -> None:
        for _ in range(n):
            await storage.append_audit(
                {
                    "event": "service.start",
                    "service": service,
                    "instance_id": f"{service}_1",
                    "system_user_id": None,
                    "subject_kind": "service",
                    "subject_id": None,
                    "evidence_ref": None,
                    "trace_id": None,
                    "span_id": None,
                    "payload": {"worker": service, "uuid": str(uuid4())},
                    "at": datetime.now(tz=UTC),
                }
            )

    try:
        asyncio.run(run())
    except Exception as exc:  # pragma: no cover — diagnostic on failure only
        return f"FAIL({service}): {type(exc).__name__}: {exc}"
    return "OK"


@pytest.mark.unit
def test_four_processes_append_audit_chain_linear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Pre-init schema in the parent so the audit-chain race is what's tested,
    # not the init race (which has its own test).
    from eyenet.storage.factory import get_repository

    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    get_repository(data_dir=tmp_path)

    workers = [(str(tmp_path), f"svc{i}", 25) for i in range(4)]
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_append_worker, workers)

    assert results == ["OK"] * 4, f"workers failed: {results}"

    # Now read the chain back in the parent and walk it forward.
    storage = get_repository(data_dir=tmp_path)

    async def read_chain() -> list[tuple[str, str, str]]:
        rows = await storage.all_audit()
        return [(r.event, r.prev_hash, r.self_hash) for r in rows]

    chain = asyncio.run(read_chain())
    assert len(chain) == 100, f"expected 100 rows, got {len(chain)}"

    # No two rows share a prev_hash — that was the fork symptom.
    prev_hashes = [c[1] for c in chain]
    assert len(set(prev_hashes)) == 100, "duplicate prev_hash values — chain has forked"

    # Forward walk: each row's prev_hash matches the previous row's self_hash.
    expected_prev = GENESIS_PREV_HASH
    for i, (_event, prev, self_hash) in enumerate(chain):
        assert prev == expected_prev, (
            f"chain broken at row {i}: prev={prev[:8]} expected={expected_prev[:8]}"
        )
        expected_prev = self_hash
