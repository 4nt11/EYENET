# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for the M10 document-upload handler (slice 8 — async).

Calls the handler as a plain coroutine (the ASGI route is exercised by the
integration suite, which coverage cannot trace). The endpoint no longer
classifies inline: it STAGES a provisional CLASSIFIED row and PUBLISHES a
classify trigger, returning 202. The settle happens off-path in the
ClassifierService. So the assertions here are: provisional persisted +
trigger published — no nsjail, no network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.documents.api_upload_document import documents_upload
from eyenet.contracts._base import BusEnvelope
from eyenet.contracts.classify_events import SUBJECT_DOCUMENT_UPLOADED
from eyenet.contracts.enums import SensitivityTier
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def mkuser() -> Callable[..., CurrentUser]:
    from uuid import uuid4

    from eyenet.contracts.enums import SystemUserRole

    def _make(*scopes: str) -> CurrentUser:
        return CurrentUser(
            user_id=uuid4(),
            username="op",
            role=SystemUserRole.ADMIN,
            effective_scopes=frozenset(scopes),
            token_expires_at=None,
        )

    return _make


class _FakeRequest:
    def __init__(self, body: bytes, content_type: str | None = None) -> None:
        self._body = body
        self.headers: dict[str, str] = {}
        if content_type is not None:
            self.headers["content-type"] = content_type

    async def body(self) -> bytes:
        return self._body


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, BusEnvelope]] = []

    async def publish(self, subject: str, envelope: BusEnvelope) -> None:
        self.published.append((subject, envelope))


async def test_upload_stages_provisional_and_publishes_trigger(
    storage: BaseRepository, tmp_path: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    request = _FakeRequest(b"%PDF-1.7 fake", content_type="application/pdf")
    publisher = _FakePublisher()
    result = await documents_upload(
        request=request,  # type: ignore[arg-type]
        current_user=mkuser("write:documents"),
        storage=storage,
        publisher=publisher,  # type: ignore[arg-type]
        data_dir=tmp_path,
        x_filename="evidence.pdf",
    )
    # Provisional CLASSIFIED by design (settles async), §0 fail-closed.
    assert result.tier is SensitivityTier.CLASSIFIED
    assert result.sha256
    assert result.review_required is False

    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.classifier_tier is SensitivityTier.CLASSIFIED
    assert row.filename == "evidence.pdf"
    assert row.mime == "application/pdf"
    assert row.extracted_text is None  # not yet classified

    # The classify trigger was published for exactly this document.
    assert len(publisher.published) == 1
    subject, envelope = publisher.published[0]
    assert subject == SUBJECT_DOCUMENT_UPLOADED
    assert envelope.document_id == result.document_id  # type: ignore[attr-defined]
