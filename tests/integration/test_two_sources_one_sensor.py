"""M7 — second source proof.

The Telegram collector (M2) and the Matrix collector (M7) coexist on a
single `MemoryBus`, alongside one sensor subscribed to `raw.message.>`.
The abstract factory holds iff:

- Each collector has its own deterministic `instance_id` (PLAN §2.1).
- Subjects partition cleanly: `raw.message.telegram.*` and
  `raw.message.matrix.*` never cross-pollinate.
- Per-source `evidence_ref` prefixes are honored.
- Each collector emits its own `service.start` audit row under its own
  service name.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.matrix.stub import MatrixCollectorStub
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.sensor.skeleton import SensorSkeleton
from eyenet.service import run_service
from eyenet.storage import SQLiteStorage

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/corpora"
_TG_FIXTURE = _FIXTURES / "synthetic_small.jsonl"
_MX_FIXTURE = _FIXTURES / "synthetic_matrix.jsonl"


def _setup_pool(tmp_path: Path) -> Path:
    tg_session = tmp_path / "tg_alpha.session"
    tg_session.touch()
    entries = [
        IdentityFileEntry(
            name="tg_alpha",
            source=SourceKind.TELEGRAM,
            session_path=str(tg_session),
            cooldown_seconds=0,
        ),
        IdentityFileEntry(
            name="alpha_mx",
            source=SourceKind.MATRIX,
            matrix_homeserver_url="https://example.org",
            matrix_user_id="@alpha_mx:example.org",
            matrix_access_token="stub-token",  # noqa: S106 — test fixture, not a real token
            cooldown_seconds=0,
        ),
    ]
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=entries), cfg_path)
    return cfg_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_sources_one_sensor(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path)
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = SQLiteStorage(tmp_path / "data")

    sensor = SensorSkeleton(bus=bus, storage=storage)
    tg = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_TG_FIXTURE,
    )
    mx = MatrixCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="alpha_mx",
        fixture_path=_MX_FIXTURE,
    )

    # Distinct instance_ids — different sources MUST yield different ids
    # even if they shared an identity name. They don't here either way.
    assert tg.instance_id != mx.instance_id

    captured: list[tuple[str, bytes]] = []

    original_subscribe = sensor.on_subscribe

    async def patched_subscribe() -> None:
        await original_subscribe()

        async def _recorder(subject: str, payload: bytes, _h: dict[str, str]) -> None:
            captured.append((subject, payload))

        await bus.subscribe("raw.message.>", _recorder)

    sensor.on_subscribe = patched_subscribe  # type: ignore[method-assign]

    sensor_task = asyncio.create_task(run_service(sensor))
    tg_task = asyncio.create_task(run_service(tg, tick_interval=0.01))
    mx_task = asyncio.create_task(run_service(mx, tick_interval=0.01))

    await asyncio.sleep(0.3)

    await sensor.shutdown()
    await tg.shutdown()
    await mx.shutdown()
    await asyncio.gather(sensor_task, tg_task, mx_task)

    # 3 + 3 = 6 envelopes across both sources.
    assert len(captured) == 6

    subjects = {s for s, _ in captured}
    tg_subject = f"raw.message.telegram.{tg.instance_id}"
    mx_subject = f"raw.message.matrix.{mx.instance_id}"
    assert tg_subject in subjects
    assert mx_subject in subjects

    # Per-source partitioning: no Matrix envelope ever lands on a Telegram
    # subject and vice versa.
    by_source: dict[SourceKind, list[str]] = {SourceKind.TELEGRAM: [], SourceKind.MATRIX: []}
    by_subject_source: dict[SourceKind, list[str]] = {
        SourceKind.TELEGRAM: [],
        SourceKind.MATRIX: [],
    }
    for subject, payload in captured:
        env = RawMessageEnvelope.model_validate_json(payload)
        by_source[env.source].append(env.evidence_ref)
        if subject.startswith("raw.message.telegram."):
            by_subject_source[SourceKind.TELEGRAM].append(env.evidence_ref)
        elif subject.startswith("raw.message.matrix."):
            by_subject_source[SourceKind.MATRIX].append(env.evidence_ref)

    assert len(by_source[SourceKind.TELEGRAM]) == 3
    assert len(by_source[SourceKind.MATRIX]) == 3
    # Envelope source matches subject prefix — no cross-pollination.
    assert by_source[SourceKind.TELEGRAM] == by_subject_source[SourceKind.TELEGRAM]
    assert by_source[SourceKind.MATRIX] == by_subject_source[SourceKind.MATRIX]

    # Evidence-ref prefixes line up with the source they came from.
    assert all(r.startswith("telegram:") for r in by_source[SourceKind.TELEGRAM])
    assert all(r.startswith("matrix:") for r in by_source[SourceKind.MATRIX])

    # Audit log: each collector wrote service.start under its own name.
    rows = await storage.audit.all()
    services = {r.service for r in rows}
    assert {"sensor", "collector.telegram", "collector.matrix"} <= services

    await storage.close()
