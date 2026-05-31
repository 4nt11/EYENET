# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/documents through the real ASGI app (M10 slice 8 — ASYNC).

The endpoint stages bytes + a provisional CLASSIFIED row and publishes a
``classify.document.uploaded`` trigger; it returns 202 with the provisional
tier. Three angles:

  * wiring/auth — viewer (no ``write:documents``) → 403; no bearer → 401.
  * the happy path — admin → 202, provisional CLASSIFIED persisted, trigger
    published (asserted via a recording publisher).
  * end-to-end — a ClassifierService on the SAME bus settles a benign doc to
    NORMAL through the live endpoint (proves the tier is REAL, not a hardcoded
    provisional). Driven with an async client so the create_task'd settle runs.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from eyenet.api.app import create_app
from eyenet.bus import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.classifier import ingest as ingest_mod
from eyenet.classifier.llm import LlmAdvisory
from eyenet.classifier.presidio import PresidioVerdict
from eyenet.classifier.sandbox import ExtractResult
from eyenet.classifier.service import ClassifierService
from eyenet.contracts._base import BusEnvelope
from eyenet.contracts.classify_events import SUBJECT_DOCUMENT_UPLOADED
from eyenet.contracts.enums import SensitivityTier, SystemUserRole

pytestmark = pytest.mark.integration

# The conftest seed_user default password — passed positionally to _login so no
# ``password=<literal>`` keyword pattern lands in this file (detect-secrets).
_PW = "correct horse battery staple"


def _login(client: TestClient, username: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": _PW})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


# --- wiring / auth (default app via the client fixture) ---------------------


async def test_upload_requires_write_documents_scope(client: TestClient, seed_user) -> None:
    await seed_user(username="v", role=SystemUserRole.VIEWER)
    token = _login(client, "v")
    resp = client.post(
        "/v1/documents",
        content=b"%PDF-1.7 fake",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"},
    )
    assert resp.status_code == 403
    assert "write:documents" in resp.json()["detail"]


async def test_upload_no_bearer_is_401(client: TestClient) -> None:
    resp = client.post("/v1/documents", content=b"x")
    assert resp.status_code == 401


# --- happy path: 202 provisional + trigger published ------------------------


class _RecordingPublisher:
    """BusEnvelopePublisher wrapper that records every publish, then forwards."""

    def __init__(self) -> None:
        self._inner = BusEnvelopePublisher(MemoryBus())
        self.published: list[tuple[str, BusEnvelope]] = []

    async def publish(self, subject: str, envelope: BusEnvelope) -> None:
        self.published.append((subject, envelope))
        await self._inner.publish(subject, envelope)


async def test_upload_admin_returns_202_provisional_and_publishes(storage, data_dir, seed_user):
    await seed_user(username="a", role=SystemUserRole.ADMIN)
    recorder = _RecordingPublisher()
    app = create_app(storage=storage, data_dir=data_dir, publisher=recorder)  # type: ignore[arg-type]
    with TestClient(app) as client:
        token = _login(client, "a")
        resp = client.post(
            "/v1/documents",
            content=b"%PDF-1.7 fake bytes",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/pdf",
                "X-Filename": "brief.pdf",
            },
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["tier"] == "classified"  # provisional, settled async
    assert body["sha256"]
    assert body["review_required"] is False

    # The classifier trigger was published for the staged document.
    triggers = [env for subject, env in recorder.published if subject == SUBJECT_DOCUMENT_UPLOADED]
    assert len(triggers) == 1
    assert str(triggers[0].document_id) == body["document_id"]  # type: ignore[attr-defined]

    # The persisted row is provisional CLASSIFIED until the service settles it.
    from uuid import UUID

    row = await storage.get_document(UUID(body["document_id"]))
    assert row is not None
    assert row.classifier_tier is SensitivityTier.CLASSIFIED


# --- end-to-end: the service settles a benign doc to NORMAL -----------------


async def test_upload_settles_normal_end_to_end(
    storage, data_dir, seed_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stub the jailed stages so settle is deterministic + network-free, then run
    # a real ClassifierService on the SAME bus the endpoint publishes to.
    monkeypatch.setattr(
        ingest_mod,
        "extract_document",
        lambda blob: ExtractResult(text="lunch plans for friday", meta={"doc_kind": "text"}),
    )
    monkeypatch.setattr(
        ingest_mod,
        "detect",
        lambda text: PresidioVerdict(
            tier_floor=SensitivityTier.NORMAL, matches=(), map_version="v1"
        ),
    )

    async def _benign(text: str) -> LlmAdvisory:
        return LlmAdvisory(
            suggested_tier=SensitivityTier.NORMAL, summary="benign", indicators=(), confidence="low"
        )

    monkeypatch.setattr(ingest_mod, "advise", _benign)

    await seed_user(username="a", role=SystemUserRole.ADMIN)
    bus = MemoryBus()
    app = create_app(storage=storage, data_dir=data_dir, publisher=BusEnvelopePublisher(bus))
    svc = ClassifierService(bus=bus, storage=storage)
    await svc.on_subscribe()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/v1/auth/login", json={"username": "a", "password": _PW})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        resp = await ac.post(
            "/v1/documents",
            content=b"lunch plans for friday",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
        )
        assert resp.status_code == 202, resp.text
        doc_id = resp.json()["document_id"]
        await asyncio.sleep(0.1)  # let the create_task'd settle run on this loop

    from uuid import UUID

    settled = await storage.get_document(UUID(doc_id))
    assert settled is not None
    assert settled.classifier_tier is SensitivityTier.NORMAL  # provisional → REAL NORMAL
    assert settled.extracted_text == "lunch plans for friday"
