"""Schema-level CHECK on DocumentTable sensitivity columns (§4.9, SQLite probe).

Mirrors ``test_reclassify_schema_sqlite.py``: the storage CHECK enforces
monotone-up (operator_tier_override, if set, must rank >= classifier_tier) —
the last line of defence even against a hand-crafted INSERT. SQLite-impl probe
⇒ env-pinned + ``_sqlite`` filename suffix per the convention.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import SensitivityTier
from eyenet.models.document import DocumentTable
from eyenet.storage.factory import get_repository

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 5, 31, tzinfo=UTC)


@pytest.fixture
def doc_session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)


def _doc(**overrides: object) -> DocumentTable:
    defaults: dict[str, object] = {
        "sha256": "0" * 64,
        "mime": "application/pdf",
        "size_bytes": 1024,
        "uploaded_at": _NOW,
        "ingested_at": _NOW,
    }
    defaults.update(overrides)
    return DocumentTable(**defaults)  # type: ignore[arg-type]


def test_default_classifier_is_normal(doc_session: Session) -> None:
    d = _doc()
    doc_session.add(d)
    doc_session.commit()
    doc_session.refresh(d)
    assert d.classifier_tier is SensitivityTier.NORMAL
    assert d.operator_tier_override is None


def test_promote_normal_to_classified_accepted(doc_session: Session) -> None:
    doc_session.add(
        _doc(
            classifier_tier=SensitivityTier.NORMAL,
            operator_tier_override=SensitivityTier.CLASSIFIED,
        )
    )
    doc_session.commit()


def test_demote_classified_to_normal_rejected(doc_session: Session) -> None:
    doc_session.add(
        _doc(
            classifier_tier=SensitivityTier.CLASSIFIED,
            operator_tier_override=SensitivityTier.NORMAL,
        )
    )
    with pytest.raises(IntegrityError):
        doc_session.commit()


def test_same_tier_accepted(doc_session: Session) -> None:
    doc_session.add(
        _doc(
            classifier_tier=SensitivityTier.RESTRICTED,
            operator_tier_override=SensitivityTier.RESTRICTED,
        )
    )
    doc_session.commit()
