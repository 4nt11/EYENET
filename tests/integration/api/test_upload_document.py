# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/documents through the real ASGI app (M10 slice 7).

Exercises the routing + ``get_data_dir`` dependency + ``write:documents`` scope
gate that the direct-call unit test bypasses. The app's sandbox is unarmed in
the test process, so the upload settles CLASSIFIED (§0) — the assertion is on
the wiring (auth, scope, persistence, response shape), not the tier value.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eyenet.classifier import ingest as ingest_mod
from eyenet.classifier.llm import LlmAdvisory
from eyenet.classifier.presidio import PresidioVerdict
from eyenet.classifier.sandbox import ExtractResult
from eyenet.contracts.enums import SensitivityTier, SystemUserRole

pytestmark = pytest.mark.integration


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def test_upload_requires_write_documents_scope(client: TestClient, seed_user) -> None:
    await seed_user(username="v", password="pw", role=SystemUserRole.VIEWER)
    token = _login(client, "v", "pw")
    resp = client.post(
        "/v1/documents",
        content=b"%PDF-1.7 fake",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"},
    )
    assert resp.status_code == 403
    assert "write:documents" in resp.json()["detail"]


async def test_upload_admin_classifies_and_returns_201(client: TestClient, seed_user) -> None:
    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    token = _login(client, "a", "pw")
    resp = client.post(
        "/v1/documents",
        content=b"%PDF-1.7 fake bytes",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/pdf",
            "X-Filename": "brief.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tier"] == "classified"  # unarmed sandbox → §0 fail-closed
    assert body["sha256"]
    assert body["review_required"] is False


async def test_upload_benign_document_settles_normal(
    client: TestClient, seed_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The OPPOSITE of the fail-closed case: with extraction + PII detection
    # succeeding on benign content, the SAME endpoint must return NORMAL — proof
    # the response tier reflects real classification, not a hardcoded CLASSIFIED.
    # The jailed stages + the advisory LLM are stubbed so the path is
    # deterministic and network-free (the real sandbox is unarmed in-process).
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

    await seed_user(username="a", password="pw", role=SystemUserRole.ADMIN)
    token = _login(client, "a", "pw")
    resp = client.post(
        "/v1/documents",
        content=b"lunch plans for friday",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["tier"] == "normal"
    assert body["review_required"] is False


async def test_upload_no_bearer_is_401(client: TestClient) -> None:
    resp = client.post("/v1/documents", content=b"x")
    assert resp.status_code == 401
