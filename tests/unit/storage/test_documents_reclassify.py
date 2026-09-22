# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct storage-mixin tests for DocumentsMixin.reclassify_document (§4.9).

Exercised against an in-memory ``BaseRepository`` via the factory (CLAUDE.md
§2.3 Rule 2 - no direct backend import), crediting the operator monotone-promote
branches the ASGI layer cannot trace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.errors import ReclassifyDemotionError
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


async def _put_doc(storage: BaseRepository, tier: SensitivityTier = SensitivityTier.NORMAL):
    now = datetime.now(tz=UTC)
    return await storage.put_document(
        DocumentRow(
            sha256="d" * 64,
            mime="application/pdf",
            size_bytes=10,
            uploaded_at=now,
            ingested_at=now,
            classifier_tier=tier,
        )
    )


async def _reclassify(storage: BaseRepository, document_id, new_tier, reason: str):
    return await storage.reclassify_document(
        document_id=document_id,
        new_tier=new_tier,
        operator_user_id=uuid4(),
        reason=reason,
        grant_id=uuid4(),
        operator_signature_pubkey_fingerprint="fp0",
        service="test",
        instance_id="t0",
    )


async def test_reclassify_document_promote_succeeds_and_audits(storage: BaseRepository) -> None:
    doc_id = await _put_doc(storage, tier=SensitivityTier.NORMAL)
    outcome = await _reclassify(
        storage, doc_id, SensitivityTier.RESTRICTED, "promoting doc after operator review"
    )
    assert outcome.operator_tier_override is SensitivityTier.RESTRICTED
    assert outcome.effective_tier is SensitivityTier.RESTRICTED
    assert outcome.prior_effective_tier is SensitivityTier.NORMAL
    assert outcome.classifier_tier is SensitivityTier.NORMAL
    assert outcome.audit_event_id is not None
    # The row reflects the promotion.
    row = await storage.get_document(doc_id)
    assert row is not None
    assert row.operator_tier_override is SensitivityTier.RESTRICTED


async def test_reclassify_document_demotion_is_rejected(storage: BaseRepository) -> None:
    doc_id = await _put_doc(storage, tier=SensitivityTier.CLASSIFIED)
    with pytest.raises(ReclassifyDemotionError):
        await _reclassify(
            storage, doc_id, SensitivityTier.RESTRICTED, "attempting to demote which is forbidden"
        )


async def test_reclassify_document_same_tier_is_noop(storage: BaseRepository) -> None:
    doc_id = await _put_doc(storage, tier=SensitivityTier.NORMAL)
    outcome = await _reclassify(
        storage, doc_id, SensitivityTier.NORMAL, "same-tier reclassify should be a no-op"
    )
    assert outcome.operator_tier_override is None
    assert outcome.audit_event_id is None


async def test_reclassify_document_missing_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await _reclassify(
            storage, uuid4(), SensitivityTier.RESTRICTED, "reclassify a missing document row"
        )


async def test_reclassify_document_short_reason_raises(storage: BaseRepository) -> None:
    doc_id = await _put_doc(storage)
    with pytest.raises(ValueError, match="16 characters"):
        await _reclassify(storage, doc_id, SensitivityTier.RESTRICTED, "too short")
