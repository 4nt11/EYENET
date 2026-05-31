"""Flat-repo ``put_document`` / ``get_document`` round-trip (DocumentsMixin).

Types against ``BaseRepository`` + constructs via ``get_repository`` per Rule 2
([[feedback_use_basereo_abstraction_in_tests]]) — the schema-level CHECK probe
that pins SQLite lives in ``test_document_schema_sqlite.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _row(**over: object) -> DocumentRow:
    base: dict[str, object] = {
        "sha256": "a" * 64,
        "mime": "application/pdf",
        "size_bytes": 2048,
        "doc_kind": "pdf",
        "filename": "memo.pdf",
        "storage_uri": "/data/documents/aa/" + "a" * 64 + ".bin",
        "extracted_text": "hello world",
        "embedded_meta": {"author": "alice", "producer": "LibreOffice"},
        "classification": {"tier": "restricted", "ruleset_version": "v3"},
        "review_required": False,
        "uploaded_at": _NOW,
        "ingested_at": _NOW,
        "classifier_tier": SensitivityTier.RESTRICTED,
    }
    base.update(over)
    return DocumentRow(**base)  # type: ignore[arg-type]


async def test_put_then_get_round_trips(storage: BaseRepository) -> None:
    row = _row()
    doc_id = await storage.put_document(row)
    assert doc_id == row.id  # id is pre-generated on the contract, not reassigned

    fetched = await storage.get_document(doc_id)
    assert fetched is not None
    assert fetched.sha256 == "a" * 64
    assert fetched.classifier_tier is SensitivityTier.RESTRICTED
    assert fetched.embedded_meta == {"author": "alice", "producer": "LibreOffice"}
    assert fetched.classification == {"tier": "restricted", "ruleset_version": "v3"}
    assert fetched.extracted_text == "hello world"


async def test_get_missing_returns_none(storage: BaseRepository) -> None:
    assert await storage.get_document(uuid4()) is None


async def test_json_columns_default_empty(storage: BaseRepository) -> None:
    row = _row(embedded_meta={}, classification={})
    doc_id = await storage.put_document(row)
    fetched = await storage.get_document(doc_id)
    assert fetched is not None
    assert fetched.embedded_meta == {}
    assert fetched.classification == {}


@pytest.mark.parametrize("tier", list(SensitivityTier))
async def test_every_tier_round_trips(storage: BaseRepository, tier: SensitivityTier) -> None:
    doc_id = await storage.put_document(_row(classifier_tier=tier))
    fetched = await storage.get_document(doc_id)
    assert fetched is not None
    assert fetched.classifier_tier is tier


_LATER = datetime(2026, 5, 31, 12, 5, tzinfo=UTC)


async def test_settle_overwrites_provisional_classified(storage: BaseRepository) -> None:
    # Stage a provisional CLASSIFIED row (what stage_document persists), then
    # settle it down to the computed tier once the async pipeline finishes.
    provisional = _row(
        classifier_tier=SensitivityTier.CLASSIFIED,
        extracted_text=None,
        embedded_meta={},
        classification={},
        review_required=False,
    )
    doc_id = await storage.put_document(provisional)

    await storage.settle_document_classification(
        doc_id,
        tier=SensitivityTier.NORMAL,
        extracted_text="lunch plans",
        embedded_meta={"author": "bob"},
        classification={"tier": "normal", "ruleset_version": "v3"},
        review_required=False,
        ingested_at=_LATER,
    )

    settled = await storage.get_document(doc_id)
    assert settled is not None
    assert settled.classifier_tier is SensitivityTier.NORMAL  # provisional → lowered
    assert settled.extracted_text == "lunch plans"
    assert settled.embedded_meta == {"author": "bob"}
    assert settled.classification == {"tier": "normal", "ruleset_version": "v3"}
    # SQLite stores datetimes naive (tzinfo stripped on round-trip, treated UTC).
    assert settled.ingested_at.replace(tzinfo=None) == _LATER.replace(tzinfo=None)


async def test_settle_is_idempotent_on_replay(storage: BaseRepository) -> None:
    doc_id = await storage.put_document(_row(classifier_tier=SensitivityTier.CLASSIFIED))
    kwargs = {
        "tier": SensitivityTier.RESTRICTED,
        "extracted_text": "x",
        "embedded_meta": {},
        "classification": {"tier": "restricted"},
        "review_required": True,
        "ingested_at": _LATER,
    }
    await storage.settle_document_classification(doc_id, **kwargs)  # type: ignore[arg-type]
    await storage.settle_document_classification(doc_id, **kwargs)  # type: ignore[arg-type]
    settled = await storage.get_document(doc_id)
    assert settled is not None
    assert settled.classifier_tier is SensitivityTier.RESTRICTED
    assert settled.review_required is True


async def test_settle_missing_document_raises(storage: BaseRepository) -> None:
    with pytest.raises(ValueError, match="not found"):
        await storage.settle_document_classification(
            uuid4(),
            tier=SensitivityTier.NORMAL,
            extracted_text=None,
            embedded_meta={},
            classification={},
            review_required=False,
            ingested_at=_LATER,
        )
