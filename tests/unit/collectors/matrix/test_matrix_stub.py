"""`MatrixCollectorStub` — fixture replay + envelope shape."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.matrix.stub import MatrixCollectorStub
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.service import run_service
from eyenet.storage import SQLiteStorage

_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/corpora/synthetic_matrix.jsonl"


def _setup_pool(tmp_path: Path, name: str) -> Path:
    entry = IdentityFileEntry(
        name=name,
        source=SourceKind.MATRIX,
        matrix_homeserver_url="https://example.org",
        matrix_user_id=f"@{name}:example.org",
        matrix_access_token="stub-token",  # noqa: S106 — test fixture
        cooldown_seconds=0,
    )
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg_path)
    return cfg_path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stub_emits_matrix_envelopes(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path, "alpha_mx")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")

    captured: list[tuple[str, bytes]] = []

    async def _recorder(subject: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append((subject, payload))

    await bus.subscribe("raw.message.>", _recorder)

    coll = MatrixCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="alpha_mx",
        fixture_path=_FIXTURE,
    )
    task = asyncio.create_task(run_service(coll, tick_interval=0.01))
    # 3 fixture rows at 10ms tick = 30ms; give it some headroom.
    await asyncio.sleep(0.2)
    await coll.shutdown()
    await task

    # 3 envelopes, all on the Matrix subject for this instance.
    expected_subject_prefix = f"raw.message.matrix.{coll.instance_id}"
    assert len(captured) == 3
    for subject, payload in captured:
        assert subject == expected_subject_prefix
        env = RawMessageEnvelope.model_validate_json(payload)
        assert env.source == SourceKind.MATRIX
        assert env.evidence_ref.startswith("matrix:")
        assert env.instance_id == coll.instance_id

    await storage.close()


@pytest.mark.unit
def test_stub_instance_id_distinct_from_telegram(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path, "alpha")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")
    mx = MatrixCollectorStub(
        bus=bus, storage=storage, pool=pool, identity_name="alpha", fixture_path=None
    )
    # Same identity name on a different source MUST yield a different
    # instance_id (PLAN §2.1 collision-resistance contract).
    from eyenet.contracts.collector import compute_instance_id

    tg_id = compute_instance_id("alpha", SourceKind.TELEGRAM)
    assert mx.instance_id != tg_id
