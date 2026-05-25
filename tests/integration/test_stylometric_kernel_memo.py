"""Integration test: the M6.5 single-pass kernel + storage-fetch memo.

Proves at the sensor layer (not just at the kernel unit-test layer) that:

* For each actor dispatch, the kernel's spaCy ``nlp.pipe`` runs exactly
  ONCE across the three M6.5 primitives — not three times. The cost of
  the spaCy tagger pass is amortized across the trio.
* For each actor dispatch, ``CorpusStore.iter_since`` is called exactly
  ONCE across the eleven ``requires_full_corpus=True`` primitives (8
  meta + 3 trio) — not eleven times. The cost of the SQLite read is
  amortized across the full set.

Together these are the two performance properties M6.5 round-2 promised.
If a future refactor regresses either, this test fires.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlmodel import Session

from eyenet.bus import MemoryBus
from eyenet.collectors.telegram.stub import TelegramCollectorStub
from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.sensor.primitives import _locale_morph_kernel as kernel
from eyenet.sensor.stylometric import StylometricSensor
from eyenet.service import run_service
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/corpora/synthetic_m2.jsonl"
_NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


def _pool(tmp_path: Path) -> FileIdentityPool:
    session = tmp_path / "tg_alpha.session"
    session.touch()
    entry = IdentityFileEntry(
        name="tg_alpha", source=SourceKind.TELEGRAM, session_path=str(session), cooldown_seconds=0
    )
    cfg = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg)
    return FileIdentityPool(cfg)


async def _seed_messages(storage: BaseRepository) -> int:
    """Reuse the synthetic_m2 fixture; return the message count."""
    from tests._seed import seed_telegram_fixture  # noqa: PLC0415

    records = []
    with _FIXTURE.open() as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    await seed_telegram_fixture(storage, records, _NOW)
    return len(records)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kernel_runs_once_per_actor_dispatch(tmp_path: Path) -> None:
    """End-to-end: across the M6.5 trio, spaCy runs once per dispatch."""
    pool = _pool(tmp_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")
    msg_count = await _seed_messages(storage)

    kernel._reset_for_tests()
    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_FIXTURE,
    )

    processed: list[str] = []
    original = sensor._process

    async def _patched(env):  # type: ignore[no-untyped-def]
        processed.append(env.evidence_ref)
        await original(env)

    sensor._process = _patched  # type: ignore[method-assign]

    sensor_task = asyncio.create_task(run_service(sensor))
    collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

    # Wait for every message to be processed by the sensor.
    for _ in range(200):
        if len(processed) >= msg_count:
            break
        await asyncio.sleep(0.05)

    collector_task.cancel()
    sensor_task.cancel()
    # Only CancelledError is expected from .cancel(). Anything else
    # propagates and fails the test loudly — visibility is the rule.
    with contextlib.suppress(asyncio.CancelledError):
        await collector_task
    with contextlib.suppress(asyncio.CancelledError):
        await sensor_task

    # Each envelope dispatches all PRIMITIVES once. Before the M6.5
    # single-pass fix, the kernel ran nlp.pipe 3x per envelope (once
    # per M6.5 primitive). After the fix, it runs at most ONCE per
    # envelope. We allow ≤ msg_count to accommodate the kernel
    # short-circuiting on empty bodies / language-gate misses.
    assert kernel._stats.pipe_calls <= msg_count, (
        f"kernel ran nlp.pipe {kernel._stats.pipe_calls} times across "
        f"{msg_count} envelopes — expected ≤ {msg_count} (one per dispatch)"
    )
    # Cache hits must materially exceed misses (we get 2 hits per
    # dispatch when the trio runs, ~msg_count misses).
    assert kernel._stats.cache_hits >= 2 * kernel._stats.cache_misses, (
        f"cache_hits={kernel._stats.cache_hits} cache_misses={kernel._stats.cache_misses} — "
        "trio should produce 2 hits per actual pipe pass"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_corpus_fetched_once_per_dispatch(tmp_path: Path) -> None:
    """End-to-end: 11 requires_full_corpus primitives share ONE SQLite read."""
    pool = _pool(tmp_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")
    msg_count = await _seed_messages(storage)

    sensor = StylometricSensor(bus=bus, storage=storage)
    collector = TelegramCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="tg_alpha",
        fixture_path=_FIXTURE,
    )

    processed: list[str] = []
    original = sensor._process

    async def _patched(env):  # type: ignore[no-untyped-def]
        processed.append(env.evidence_ref)
        await original(env)

    sensor._process = _patched  # type: ignore[method-assign]

    real_iter_since = storage.iter_corpus_since
    iter_since_calls = 0

    async def counting_iter_since(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal iter_since_calls
        iter_since_calls += 1
        return await real_iter_since(*args, **kwargs)

    with patch.object(storage, "iter_corpus_since", side_effect=counting_iter_since):
        sensor_task = asyncio.create_task(run_service(sensor))
        collector_task = asyncio.create_task(run_service(collector, tick_interval=0.001))

        for _ in range(200):
            if len(processed) >= msg_count:
                break
            await asyncio.sleep(0.05)

        collector_task.cancel()
        sensor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await collector_task
        with contextlib.suppress(asyncio.CancelledError):
            await sensor_task

    # Each dispatch has 11 requires_full_corpus primitives (8 meta + 3
    # M6.5 trio) + 9 window-cursor primitives. Before the fix: ~20
    # iter_since calls per envelope. After: 1 cached full-corpus +
    # per-cursor calls. We test against the strict pre-fix upper bound
    # (msg_count * 11, i.e. every requires_full_corpus primitive re-
    # fetching) to catch a full regression.
    strict_upper = msg_count * 11
    assert iter_since_calls < strict_upper, (
        f"iter_since called {iter_since_calls} times — fix regressed; "
        f"expected far less than {strict_upper} (one per requires_full_corpus primitive)"
    )
