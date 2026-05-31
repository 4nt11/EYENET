# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for the M10 document-upload handler.

Calls the handler as a plain coroutine (the ASGI route is exercised by the
integration suite, which coverage cannot trace). The sandbox is UNARMED in the
unit process, so extraction fails closed and the doc settles CLASSIFIED (§0) —
which is exactly the right offline assertion: the handler wiring + persistence +
audit emission all run without nsjail or a network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.documents.api_upload_document import documents_upload
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


class _FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def emit(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


async def test_upload_settles_classified_offline_and_persists(
    storage: BaseRepository, tmp_path: Path, mkuser: Callable[..., CurrentUser]
) -> None:
    request = _FakeRequest(b"%PDF-1.7 fake", content_type="application/pdf")
    audit = _FakeAudit()
    result = await documents_upload(
        request=request,  # type: ignore[arg-type]
        current_user=mkuser("write:documents"),
        storage=storage,
        audit=audit,  # type: ignore[arg-type]
        data_dir=tmp_path,
        x_filename="evidence.pdf",
    )
    # Sandbox unarmed → fail-closed → CLASSIFIED (§0).
    assert result.tier is SensitivityTier.CLASSIFIED
    assert result.sha256
    row = await storage.get_document(result.document_id)
    assert row is not None
    assert row.classifier_tier is SensitivityTier.CLASSIFIED
    assert row.filename == "evidence.pdf"
    assert row.mime == "application/pdf"
    # The classification decision was audited.
    assert any(c.get("subject_kind") == "document" for c in audit.calls)
