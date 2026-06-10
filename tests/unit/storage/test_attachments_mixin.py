# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct storage-mixin tests for AttachmentsMixin (PHASE-5 read/store surface).

The PHASE-5 attachment access handlers read/store through these methods. They
are exercised here against an in-memory ``BaseRepository`` via the factory
(CLAUDE.md §2.3 Rule 2 — no direct backend import), crediting the put/get/
set-classification/reclassify branches the ASGI layer cannot trace.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.errors import ReclassifyDemotionError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _put(storage: BaseRepository, tier: SensitivityTier = SensitivityTier.NORMAL):
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=11,
            sha256="a" * 64,
            storage_uri="blob/a.bin",
            classifier_tier=tier,
        )
    )


async def test_put_then_get_roundtrips(storage: BaseRepository) -> None:
    blob_id = await _put(storage)
    row = await storage.get_attachment(blob_id)
    assert row is not None
    assert row.sha256 == "a" * 64
    assert row.classifier_tier is SensitivityTier.NORMAL


async def test_get_missing_returns_none(storage: BaseRepository) -> None:
    assert await storage.get_attachment(uuid4()) is None


async def test_set_classification_updates_tier(storage: BaseRepository) -> None:
    blob_id = await _put(storage)
    await storage.set_attachment_classification(blob_id, SensitivityTier.RESTRICTED)
    row = await storage.get_attachment(blob_id)
    assert row is not None
    assert row.classifier_tier is SensitivityTier.RESTRICTED


async def test_set_classification_missing_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.set_attachment_classification(uuid4(), SensitivityTier.NORMAL)


async def test_reclassify_promote_succeeds_and_audits(storage: BaseRepository) -> None:
    blob_id = await _put(storage, tier=SensitivityTier.NORMAL)
    updated = await storage.reclassify_attachment(
        attachment_id=blob_id,
        new_tier=SensitivityTier.RESTRICTED,
        operator_user_id=uuid4(),
        reason="promoting after manual operator review",
        service="test",
        instance_id="t0",
    )
    assert updated.operator_tier_override is SensitivityTier.RESTRICTED


async def test_reclassify_demotion_is_rejected(storage: BaseRepository) -> None:
    blob_id = await _put(storage, tier=SensitivityTier.RESTRICTED)
    with pytest.raises(ReclassifyDemotionError):
        await storage.reclassify_attachment(
            attachment_id=blob_id,
            new_tier=SensitivityTier.NORMAL,
            operator_user_id=uuid4(),
            reason="attempting to demote which is monotone-forbidden",
            service="test",
            instance_id="t0",
        )


async def test_reclassify_same_tier_is_noop(storage: BaseRepository) -> None:
    blob_id = await _put(storage, tier=SensitivityTier.NORMAL)
    updated = await storage.reclassify_attachment(
        attachment_id=blob_id,
        new_tier=SensitivityTier.NORMAL,
        operator_user_id=uuid4(),
        reason="same-tier reclassify should be a no-op",
        service="test",
        instance_id="t0",
    )
    assert updated.operator_tier_override is None


async def test_reclassify_short_reason_raises(storage: BaseRepository) -> None:
    blob_id = await _put(storage)
    with pytest.raises(ValueError, match="16 characters"):
        await storage.reclassify_attachment(
            attachment_id=blob_id,
            new_tier=SensitivityTier.RESTRICTED,
            operator_user_id=uuid4(),
            reason="too short",
            service="test",
            instance_id="t0",
        )


async def test_reclassify_missing_attachment_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.reclassify_attachment(
            attachment_id=uuid4(),
            new_tier=SensitivityTier.RESTRICTED,
            operator_user_id=uuid4(),
            reason="reclassify a missing attachment row",
            service="test",
            instance_id="t0",
        )
