"""`set_attachment_classification` — the classifier-authoritative tier stamp.

Distinct from ``reclassify_attachment`` (operator promote-only). Types against
``BaseRepository`` + ``get_repository`` per Rule 2.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from eyenet.contracts.enums import AttachmentKind, SensitivityTier
from eyenet.contracts.message import AttachmentRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _attachment(**over: object) -> AttachmentRow:
    base: dict[str, object] = {
        "message_id": uuid4(),
        "kind": AttachmentKind.DOCUMENT,
        "mime": "application/pdf",
        "size_bytes": 4096,
        "sha256": "b" * 64,
        "storage_uri": "/data/attachments/telegram/abcd1234/bb/" + "b" * 64 + ".bin",
        "classifier_tier": SensitivityTier.CLASSIFIED,  # provisional at collector insert
    }
    base.update(over)
    return AttachmentRow(**base)  # type: ignore[arg-type]


async def test_get_attachment_round_trips_with_tier(storage: BaseRepository) -> None:
    # Regression: AttachmentRow now has field-parity with the table, so
    # get_attachment no longer raises on the tier columns.
    aid = await storage.put_attachment(_attachment())
    got = await storage.get_attachment(aid)
    assert got is not None
    assert got.classifier_tier is SensitivityTier.CLASSIFIED
    assert got.storage_uri is not None


async def test_set_attachment_classification_settles_provisional(storage: BaseRepository) -> None:
    aid = await storage.put_attachment(_attachment(classifier_tier=SensitivityTier.CLASSIFIED))
    await storage.set_attachment_classification(aid, SensitivityTier.NORMAL)
    got = await storage.get_attachment(aid)
    assert got is not None
    assert got.classifier_tier is SensitivityTier.NORMAL


async def test_set_attachment_classification_is_idempotent(storage: BaseRepository) -> None:
    aid = await storage.put_attachment(_attachment())
    await storage.set_attachment_classification(aid, SensitivityTier.RESTRICTED)
    await storage.set_attachment_classification(aid, SensitivityTier.RESTRICTED)
    got = await storage.get_attachment(aid)
    assert got is not None
    assert got.classifier_tier is SensitivityTier.RESTRICTED


async def test_set_attachment_classification_missing_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.set_attachment_classification(uuid4(), SensitivityTier.NORMAL)
