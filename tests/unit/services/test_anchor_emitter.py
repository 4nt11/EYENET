# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the §5.9 anchor emitter + anchor storage reads."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from eyenet.bus import MemoryBus
from eyenet.contracts.audit import GENESIS_PREV_HASH
from eyenet.crypto import build_anchor_canonical, load_anchor_key, verify_signature
from eyenet.models._base import new_uuid7
from eyenet.services.anchor_emitter import AnchorEmitter
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _emitter(storage: BaseRepository, tmp_path) -> AnchorEmitter:
    return AnchorEmitter(bus=MemoryBus(), storage=storage, data_dir=tmp_path)


async def test_emit_records_verifiable_anchor(storage: BaseRepository, tmp_path) -> None:
    await _emitter(storage, tmp_path).emit_anchor()

    rows = await storage.list_anchors(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row.anchor_seq == 0

    signer = load_anchor_key(tmp_path)
    pub = Ed25519PublicKey.from_public_bytes(signer.verifying_key_bytes)
    raw = base64.urlsafe_b64decode(row.signature.removeprefix("ed25519:"))
    canonical = build_anchor_canonical(
        deployment_id=row.deployment_id,
        anchor_seq=row.anchor_seq,
        anchored_at=row.anchored_at.isoformat(),
        audit_head=row.audit_head,
        journal_head=row.journal_head,
    )
    assert verify_signature(pub, canonical, raw) is True


async def test_seq_increments_and_count(storage: BaseRepository, tmp_path) -> None:
    emitter = _emitter(storage, tmp_path)
    await emitter.emit_anchor()
    await emitter.emit_anchor()
    assert await storage.count_anchors() == 2
    seqs = {r.anchor_seq for r in await storage.list_anchors(limit=10)}
    assert seqs == {0, 1}


async def test_audit_head_genesis_then_populated(storage: BaseRepository) -> None:
    assert await storage.audit_head() == GENESIS_PREV_HASH
    await storage.append_audit(
        {
            "id": new_uuid7(),
            "event": "eyenet.test.x",
            "service": "test",
            "instance_id": "t0",
            "system_user_id": None,
            "subject_kind": "test",
            "subject_id": None,
            "evidence_ref": None,
            "trace_id": None,
            "span_id": None,
            "payload": {},
            "at": datetime.now(tz=UTC),
        }
    )
    head = await storage.audit_head()
    assert head != GENESIS_PREV_HASH
    assert len(head) == 64
