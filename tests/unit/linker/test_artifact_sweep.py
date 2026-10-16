# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checksum sweep: purge wallet artifacts failing the coded gate, with cascade."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.linker.artifact_sweep import sweep_invalid_crypto_artifacts
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 5, tzinfo=UTC)
_MD5 = "3c38837bcd649592b2de5e87c3dbb3e2"  # hex hash the old regex mis-stored as BTC
_GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # real P2PKH


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _count(storage: BaseRepository, table: str) -> int:
    with storage.sync_engine.connect() as c:  # type: ignore[attr-defined]
        return c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608


async def _put(storage: BaseRepository, kind: str, value: str) -> object:
    return await storage.put_infrastructure_artifact(
        kind=kind, value=value, first_seen_at_ingest=_NOW, last_seen_at_ingest=_NOW
    )


async def test_dry_run_reports_but_keeps(storage: BaseRepository) -> None:
    await _put(storage, "wallet_btc", _GENESIS)
    await _put(storage, "wallet_btc", _MD5)
    report = await sweep_invalid_crypto_artifacts(storage, apply=False)
    assert report.checked == 2
    assert report.invalid == 1
    assert report.deleted == 0
    assert ("wallet_btc", _MD5) in report.invalid_samples
    assert _count(storage, "infrastructure_artifact") == 2  # dry-run deletes nothing


async def test_apply_deletes_invalid_keeps_valid(storage: BaseRepository) -> None:
    await _put(storage, "wallet_btc", _GENESIS)
    await _put(storage, "wallet_btc", _MD5)
    await _put(storage, "email", "x@y.com")  # non-crypto kind: never gated, never touched
    report = await sweep_invalid_crypto_artifacts(storage, apply=True)
    assert (report.invalid, report.deleted) == (1, 1)
    present = {
        (row[0].kind, row[0].value)
        for row in await storage.list_infrastructure_artifacts(limit=50, offset=0)
    }
    assert ("wallet_btc", _GENESIS) in present
    assert ("email", "x@y.com") in present
    assert ("wallet_btc", _MD5) not in present


async def test_apply_cascades_mentions(storage: BaseRepository) -> None:
    from eyenet.models import MessageTable
    from eyenet.models._base import new_uuid7

    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=_NOW)
    gid, _ = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHANNEL, title="g", seen_at=_NOW
    )
    actor, _ = await storage.upsert_actor(
        source_id=src,
        actor_key="a:1",
        platform_userid="1",
        handle=None,
        display_name="b",
        seen_at=_NOW,
    )
    mid = new_uuid7()
    await storage.put_message(
        MessageTable(
            id=mid,
            source_id=src,
            group_id=gid,
            actor_id=actor,
            platform_msgid="m1",
            evidence_ref="telegram:g:1",
            body=_MD5,
            length_chars=len(_MD5),
            length_words=1,
            sent_at_source=_NOW,
            ingested_at=_NOW,
        ),
        None,
    )
    bad = await _put(storage, "wallet_btc", _MD5)
    await storage.record_artifact_mention(
        artifact_id=bad.id,  # type: ignore[attr-defined]
        message_id=mid,
        char_offset=0,
        ts=_NOW,
    )
    assert _count(storage, "infrastructure_artifact_mention") == 1

    await sweep_invalid_crypto_artifacts(storage, apply=True)

    assert _count(storage, "infrastructure_artifact") == 0
    assert _count(storage, "infrastructure_artifact_mention") == 0  # cascaded with the artifact


async def test_idempotent_second_run_is_noop(storage: BaseRepository) -> None:
    await _put(storage, "wallet_btc", _GENESIS)
    await _put(storage, "wallet_btc", _MD5)
    await sweep_invalid_crypto_artifacts(storage, apply=True)
    report2 = await sweep_invalid_crypto_artifacts(storage, apply=True)
    assert (report2.checked, report2.invalid, report2.deleted) == (1, 0, 0)
