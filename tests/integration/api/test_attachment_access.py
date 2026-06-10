# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/attachments/{blob_id}/access + GET .../manifest through the ASGI app.

PHASE-5 — NORMAL-tier, client-signed, evidence-first byte serving (§5.6/§5.7).

Coverage:
  * happy path — register key → manifest → client signs → access → 200,
    streamed bytes EQUAL the stored bytes, AND a file_access_journal row exists.
  * tampered signature → 401, no bytes, no journal row.
  * body tampered after signing (``reason``) → body_hash mismatch → 401.
  * wrong ``expected_content_hash`` → 409, no serve.
  * stale ``signed_at`` (beyond freshness window) → 401.
  * non-NORMAL blob → 403 at BOTH manifest AND access, no bytes, no journal row.
  * missing blob → 404; unauthenticated → 401.
  * serve-what-was-signed — streamed bytes hash to the signed content_hash.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import ASGITransport, AsyncClient

from eyenet.api.app import create_app
from eyenet.api.v1.attachments._access_canonical import compute_access_body_hash
from eyenet.contracts.enums import AttachmentKind, SensitivityTier, SystemUserRole
from eyenet.contracts.message import AttachmentRow
from eyenet.crypto import build_canonical
from eyenet.models.file_access import FileAccessJournalTable
from eyenet.storage.sqlmodel_repo._helpers import safe_session

pytestmark = pytest.mark.integration

_PW = "correct horse battery staple"
_BLOB = b"the quick brown fox jumps over the lazy dog" * 64
_ACCESS_URL_TMPL = "/v1/attachments/{blob_id}/access"


async def _seed_blob(
    storage,
    data_dir: Path,
    *,
    tier: SensitivityTier = SensitivityTier.NORMAL,
    payload: bytes = _BLOB,
) -> tuple[UUID, str]:
    """Write real bytes to disk and persist a NORMAL AttachmentRow pointing at them."""
    sha = hashlib.sha256(payload).hexdigest()
    blob_path = data_dir / f"{sha}.bin"
    blob_path.write_bytes(payload)
    blob_id = await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=len(payload),
            sha256=sha,
            storage_uri=str(blob_path),
            classifier_tier=tier,
        )
    )
    return blob_id, sha


async def _register_key(storage, user_id: UUID) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    raw_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    await storage.record_signing_key(user_id, raw_pub)
    return private


def _sign_body(
    private: Ed25519PrivateKey,
    *,
    blob_id: UUID,
    content_hash: str,
    nonce: UUID,
    signed_at: datetime,
    reason: str = "reviewing the attachment for the case",
) -> dict[str, object]:
    body: dict[str, object] = {
        "access_nonce": str(nonce),
        "expected_content_hash": content_hash,
        "request_id": "req-" + uuid4().hex,
        "signed_at": signed_at.isoformat(),
        "reason": reason,
        "viewing_context": None,
        "case_refs": [],
    }
    # The helper consumes Python-native values; the wire body is the JSON form.
    body_hash = compute_access_body_hash({**body, "access_nonce": nonce, "signed_at": signed_at})
    canonical = build_canonical(
        "POST",
        _ACCESS_URL_TMPL.format(blob_id=blob_id),
        str(body["request_id"]),
        signed_at.isoformat(),
        body_hash,
        content_hash,
    )
    signature = private.sign(canonical)
    import base64

    body["operator_signature"] = "ed25519:" + base64.urlsafe_b64encode(signature).decode()
    return body


async def _login(ac: AsyncClient, username: str) -> str:
    resp = await ac.post("/v1/auth/login", json={"username": username, "password": _PW})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _journal_count(storage) -> int:
    """Count file_access_journal rows directly (fresh in-memory storage per test)."""
    from sqlmodel import select

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(select(FileAccessJournalTable))
        return len(result.all())


# --- happy path -------------------------------------------------------------


async def test_access_happy_path_streams_bytes_and_journals(storage, data_dir, seed_user) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}

        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        assert manifest.status_code == 200, manifest.text
        mbody = manifest.json()
        assert mbody["content_hash"] == sha
        assert mbody["tier"] == "normal"
        nonce = UUID(mbody["access_nonce"])

        body = _sign_body(
            private,
            blob_id=blob_id,
            content_hash=sha,
            nonce=nonce,
            signed_at=datetime.now(tz=UTC),
        )
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 200, resp.text
        assert resp.content == _BLOB  # streamed bytes EQUAL the stored bytes
        # serve-what-was-signed: streamed bytes hash to the signed content_hash.
        assert hashlib.sha256(resp.content).hexdigest() == sha

    assert await _journal_count(storage) == 1


# --- replay (FIX 2: single-use nonce closes the NORMAL replay hole) ----------


async def _nonce_consumed(storage, nonce: UUID) -> bool:
    """True iff the acknowledgment nonce row has been consumed (consumed_at set)."""
    from sqlmodel import select

    from eyenet.models.file_access import FileAccessAcknowledgmentTable

    async with safe_session(storage._audit_session_factory) as session:  # type: ignore[attr-defined]
        result = await session.exec(
            select(FileAccessAcknowledgmentTable).where(
                FileAccessAcknowledgmentTable.nonce == nonce
            )
        )
        row = result.first()
        return row is not None and row.consumed_at is not None


async def test_replayed_normal_access_second_is_rejected_no_second_journal(
    storage, data_dir, seed_user
) -> None:
    """A captured-and-replayed identical NORMAL POST is rejected the 2nd time.

    The first access consumes the manifest-minted single-use nonce (journal row
    written, nonce now consumed). Re-POSTing the IDENTICAL body/nonce within the
    freshness window fails — the nonce is already burned → 401, no second row.
    """
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}

        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        nonce = UUID(manifest.json()["access_nonce"])
        body = _sign_body(
            private,
            blob_id=blob_id,
            content_hash=sha,
            nonce=nonce,
            signed_at=datetime.now(tz=UTC),
        )

        # First access — succeeds, consumes the nonce, writes one journal row.
        first = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert first.status_code == 200, first.text
        assert first.content == _BLOB
        assert await _nonce_consumed(storage, nonce) is True
        assert await _journal_count(storage) == 1

        # REPLAY the byte-identical body within the freshness window — rejected
        # because the nonce is already consumed (single-use). No second row.
        replay = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert replay.status_code == 401
        assert replay.content != _BLOB

    assert await _journal_count(storage) == 1


# --- tampered signature -----------------------------------------------------


async def test_tampered_signature_is_401_no_bytes_no_journal(storage, data_dir, seed_user) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}
        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        nonce = UUID(manifest.json()["access_nonce"])
        body = _sign_body(
            private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
        )
        # Flip the last base64 char of the signature payload (still valid shape).
        sig = str(body["operator_signature"])
        body["operator_signature"] = sig[:-2] + ("A" if sig[-2] != "A" else "B") + sig[-1]
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 401
        assert resp.content != _BLOB

    assert await _journal_count(storage) == 0


# --- body tampered after signing --------------------------------------------


async def test_body_tampered_after_signing_is_401(storage, data_dir, seed_user) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}
        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        nonce = UUID(manifest.json()["access_nonce"])
        body = _sign_body(
            private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=datetime.now(tz=UTC)
        )
        # Keep the signature; mutate a signed field → body_hash diverges.
        body["reason"] = "a completely different justification entirely"
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 401

    assert await _journal_count(storage) == 0


# --- wrong expected_content_hash --------------------------------------------


async def test_wrong_expected_content_hash_is_409(storage, data_dir, seed_user) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, _sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}
        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        nonce = UUID(manifest.json()["access_nonce"])
        wrong = "c" * 64
        body = _sign_body(
            private,
            blob_id=blob_id,
            content_hash=wrong,
            nonce=nonce,
            signed_at=datetime.now(tz=UTC),
        )
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 409

    assert await _journal_count(storage) == 0


# --- stale signed_at --------------------------------------------------------


async def test_stale_signed_at_is_401(storage, data_dir, seed_user) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}
        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        nonce = UUID(manifest.json()["access_nonce"])
        stale = datetime.now(tz=UTC) - timedelta(seconds=3600)
        body = _sign_body(private, blob_id=blob_id, content_hash=sha, nonce=nonce, signed_at=stale)
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 401

    assert await _journal_count(storage) == 0


# --- non-NORMAL fail-closed at BOTH endpoints -------------------------------


@pytest.mark.parametrize(
    "tier",
    [SensitivityTier.RESTRICTED, SensitivityTier.CLASSIFIED],
)
async def test_non_normal_blob_is_403_at_both_endpoints(storage, data_dir, seed_user, tier) -> None:
    user_id = await seed_user(username="a", role=SystemUserRole.ADMIN)
    private = await _register_key(storage, user_id)
    blob_id, sha = await _seed_blob(storage, data_dir, tier=tier)
    app = create_app(storage=storage, data_dir=data_dir)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}

        manifest = await ac.get(f"/v1/attachments/{blob_id}/manifest", headers=auth)
        assert manifest.status_code == 403  # no metadata leak

        # Even a perfectly-formed signed body is refused before any byte/journal.
        body = _sign_body(
            private,
            blob_id=blob_id,
            content_hash=sha,
            nonce=uuid4(),
            signed_at=datetime.now(tz=UTC),
        )
        resp = await ac.post(f"/v1/attachments/{blob_id}/access", json=body, headers=auth)
        assert resp.status_code == 403
        assert resp.content != _BLOB

    assert await _journal_count(storage) == 0


# --- 404 / 401 --------------------------------------------------------------


async def test_missing_blob_is_404(storage, data_dir, seed_user) -> None:
    await seed_user(username="a", role=SystemUserRole.ADMIN)
    app = create_app(storage=storage, data_dir=data_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        token = await _login(ac, "a")
        auth = {"Authorization": f"Bearer {token}"}
        resp = await ac.get(f"/v1/attachments/{uuid4()}/manifest", headers=auth)
        assert resp.status_code == 404


async def test_unauthenticated_is_401(storage, data_dir, seed_user) -> None:
    blob_id, _sha = await _seed_blob(storage, data_dir)
    app = create_app(storage=storage, data_dir=data_dir)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(f"/v1/attachments/{blob_id}/manifest")
        assert resp.status_code == 401
