# SPDX-License-Identifier: AGPL-3.0-or-later
"""`MyBBCollectorStub` - parses a saved thread and emits forum envelopes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eyenet.bus import MemoryBus
from eyenet.collectors.forum.stub import MyBBCollectorStub
from eyenet.contracts.actor import actor_key
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.identity_pool import FileIdentityPool, IdentityFile, IdentityFileEntry
from eyenet.identity_pool.loader import dump
from eyenet.service import run_service
from eyenet.storage.factory import get_repository

_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "mybb_thread.html"


def _setup_pool(tmp_path: Path, name: str) -> Path:
    entry = IdentityFileEntry(name=name, source=SourceKind.FORUM, cooldown_seconds=0)
    cfg_path = tmp_path / "identities.toml"
    dump(IdentityFile(identities=[entry]), cfg_path)
    return cfg_path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stub_emits_forum_envelopes(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path, "alpha_fm")
    pool = FileIdentityPool(cfg_path)
    bus = MemoryBus()
    storage = get_repository(data_dir=tmp_path / "data")

    captured: list[tuple[str, bytes]] = []

    async def _recorder(subject: str, payload: bytes, _h: dict[str, str]) -> None:
        captured.append((subject, payload))

    await bus.subscribe("raw.message.>", _recorder)

    coll = MyBBCollectorStub(
        bus=bus,
        storage=storage,
        pool=pool,
        identity_name="alpha_fm",
        thread_path=_FIXTURE,
        thread_id="42",
        board="forum.test",
    )
    task = asyncio.create_task(run_service(coll, tick_interval=0.01))
    await asyncio.sleep(0.3)  # 2 posts at 10ms tick, ample headroom
    await coll.shutdown()
    await task

    expected_subject = f"raw.message.forum.{coll.instance_id}"
    assert len(captured) == 2
    envs = [RawMessageEnvelope.model_validate_json(p) for _, p in captured]
    for subject, _ in captured:
        assert subject == expected_subject
    for env in envs:
        assert env.source == SourceKind.FORUM
        assert env.instance_id == coll.instance_id
        assert env.evidence_ref.startswith("forum:forum.test:42:")
        assert env.platform_groupid == "42"

    # actor_key is board-scoped: derived from "<board>|<slug>", not the bare slug.
    first = envs[0]
    assert first.actor_key == actor_key(SourceKind.FORUM, "forum.test|alice")
    assert first.platform_msgid == "1001"

    await storage.close()


@pytest.mark.unit
def test_stub_no_fixture_emits_nothing(tmp_path: Path) -> None:
    cfg_path = _setup_pool(tmp_path, "beta_fm")
    pool = FileIdentityPool(cfg_path)
    coll = MyBBCollectorStub(
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        pool=pool,
        identity_name="beta_fm",
        thread_path=None,
    )
    assert coll._posts == []  # stub internal: asserting the no-fixture contract
