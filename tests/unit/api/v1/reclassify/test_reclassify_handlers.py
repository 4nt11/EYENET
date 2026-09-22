# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit tests for the §4.9 reclassify handlers.

ASGI-routed handlers do not trace for coverage (see memory project_m9_f_done),
so the handlers are called directly with an in-memory ``BaseRepository`` and a
real Ed25519 operator key. Storage self-audits the success; a fake AuditEmitter
captures the handler-side ``reclassify.rejected`` events on the refusal paths.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from eyenet.api.deps import CurrentUser, ScopeForbidden, UnprocessableError
from eyenet.api.v1.reclassify._reclassify_canonical import (
    build_reclassify_canonical,
    compute_reclassify_body_hash,
)
from eyenet.api.v1.reclassify.api_reclassify_attachment import attachments_reclassify
from eyenet.api.v1.reclassify.api_reclassify_document import documents_reclassify
from eyenet.api.v1.reclassify.api_reclassify_observation import observations_reclassify
from eyenet.api.v1.schemas.reclassify import ReclassificationRequest
from eyenet.contracts.document import DocumentRow
from eyenet.contracts.enums import (
    AttachmentKind,
    ClearanceScope,
    ReclassificationSubjectKind,
    SensitivityTier,
    SystemUserRole,
    ValueKind,
)
from eyenet.contracts.message import AttachmentRow
from eyenet.contracts.observation import ObservationRow
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

pytestmark = pytest.mark.unit

_REASON = "promoting evidence after manual operator review of case batch"
_PLACEHOLDER_SIG = "ed25519:" + ("A" * 86) + "=="


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    @property
    def service(self) -> str:
        return "test"

    @property
    def instance_id(self) -> str:
        return "t0"

    async def emit(
        self,
        *,
        event,
        subject_kind,
        subject_id=None,
        evidence_ref=None,
        system_user_id=None,
        payload=None,
    ):
        self.events.append({"event": event, "payload": dict(payload or {})})


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


@pytest.fixture
def operator_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _current_user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ANALYST,
        effective_scopes=frozenset({ClearanceScope.ADMIN_RECLASSIFY.value}),
        token_expires_at=None,
    )


def _inject_authority(
    storage: BaseRepository, key: Ed25519PrivateKey, *, grant: bool = True
) -> UUID:
    """Stub the signing-key + clearance-grant lookups the handler resolves."""
    grant_id = uuid4()
    pubkey_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    async def _active_key(_user_id):
        return pubkey_raw

    async def _grants(_user_id, *, now=None):
        if not grant:
            return []
        return [
            SimpleNamespace(
                scope=ClearanceScope.ADMIN_RECLASSIFY,
                id=grant_id,
                expires_at=datetime.now(tz=UTC) + timedelta(days=30),
            )
        ]

    storage.active_signing_key_for = _active_key  # type: ignore[method-assign]
    storage.active_clearance_grants_for = _grants  # type: ignore[method-assign]
    return grant_id


def _signed_request(
    key: Ed25519PrivateKey,
    *,
    url: str,
    content_hash: str,
    new_tier: SensitivityTier = SensitivityTier.RESTRICTED,
) -> ReclassificationRequest:
    req = ReclassificationRequest(
        new_tier=new_tier,
        reason=_REASON,
        viewing_context=None,
        operator_signature=_PLACEHOLDER_SIG,
        case_refs=[],
    )
    body_hash = compute_reclassify_body_hash(req.model_dump())
    canonical = build_reclassify_canonical(url=url, body_hash=body_hash, content_hash=content_hash)
    signature = "ed25519:" + base64.urlsafe_b64encode(key.sign(canonical)).decode()
    return req.model_copy(update={"operator_signature": signature})


def _request(url: str) -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=url))


async def _put_doc(storage: BaseRepository, tier: SensitivityTier = SensitivityTier.NORMAL) -> UUID:
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


async def _put_attachment(storage: BaseRepository) -> UUID:
    return await storage.put_attachment(
        AttachmentRow(
            message_id=uuid4(),
            kind=AttachmentKind.DOCUMENT,
            mime="application/octet-stream",
            size_bytes=11,
            sha256="a" * 64,
            storage_uri="blob/a.bin",
            classifier_tier=SensitivityTier.NORMAL,
        )
    )


async def _put_observation(storage: BaseRepository) -> UUID:
    obs_id = uuid4()
    await storage.put_observation(
        ObservationRow(
            id=obs_id,
            actor_id=uuid4(),
            primitive_namespace="ns",
            primitive_name="p",
            primitive_version="1",
            value_kind=ValueKind.ENUM_STR,
            value_enum="x",
            observed_at=datetime.now(tz=UTC),
            sensor_instance="s0",
        )
    )
    return obs_id


async def test_document_reclassify_happy(storage: BaseRepository, operator_key) -> None:
    grant_id = _inject_authority(storage, operator_key)
    doc_id = await _put_doc(storage)
    url = f"/v1/documents/{doc_id}/reclassify"
    req = _signed_request(operator_key, url=url, content_hash="d" * 64)
    result = await documents_reclassify(
        document_id=doc_id,
        body=req,
        request=_request(url),  # type: ignore[arg-type]
        current_user=_current_user(),
        storage=storage,
        audit=_FakeAudit(),  # type: ignore[arg-type]
    )
    assert result.subject_kind is ReclassificationSubjectKind.DOCUMENT
    assert result.effective_tier is SensitivityTier.RESTRICTED
    assert result.prior_effective_tier is SensitivityTier.NORMAL
    assert result.grant_id == grant_id
    assert result.audit_event_id is not None


async def test_attachment_reclassify_happy(storage: BaseRepository, operator_key) -> None:
    _inject_authority(storage, operator_key)
    blob_id = await _put_attachment(storage)
    url = f"/v1/attachments/{blob_id}/reclassify"
    req = _signed_request(operator_key, url=url, content_hash="a" * 64)
    result = await attachments_reclassify(
        blob_id=blob_id,
        body=req,
        request=_request(url),  # type: ignore[arg-type]
        current_user=_current_user(),
        storage=storage,
        audit=_FakeAudit(),  # type: ignore[arg-type]
    )
    assert result.subject_kind is ReclassificationSubjectKind.ATTACHMENT
    assert result.effective_tier is SensitivityTier.RESTRICTED


async def test_observation_reclassify_happy(storage: BaseRepository, operator_key) -> None:
    _inject_authority(storage, operator_key)
    obs_id = await _put_observation(storage)
    url = f"/v1/observations/{obs_id}/reclassify"
    # Observations carry no content blob: content_hash is the empty string.
    req = _signed_request(operator_key, url=url, content_hash="")
    result = await observations_reclassify(
        observation_id=obs_id,
        body=req,
        request=_request(url),  # type: ignore[arg-type]
        current_user=_current_user(),
        storage=storage,
        audit=_FakeAudit(),  # type: ignore[arg-type]
    )
    assert result.subject_kind is ReclassificationSubjectKind.OBSERVATION
    assert result.effective_tier is SensitivityTier.RESTRICTED


async def test_document_reclassify_bad_signature_403(storage: BaseRepository, operator_key) -> None:
    _inject_authority(storage, operator_key)
    doc_id = await _put_doc(storage)
    url = f"/v1/documents/{doc_id}/reclassify"
    # Sign over a DIFFERENT url -> canonical mismatch -> verify fails.
    req = _signed_request(operator_key, url="/v1/documents/wrong/reclassify", content_hash="d" * 64)
    audit = _FakeAudit()
    with pytest.raises(ScopeForbidden):
        await documents_reclassify(
            document_id=doc_id,
            body=req,
            request=_request(url),  # type: ignore[arg-type]
            current_user=_current_user(),
            storage=storage,
            audit=audit,  # type: ignore[arg-type]
        )
    assert any(e["payload"].get("rejection_reason") == "bad_signature" for e in audit.events)


async def test_document_reclassify_no_grant_403(storage: BaseRepository, operator_key) -> None:
    _inject_authority(storage, operator_key, grant=False)
    doc_id = await _put_doc(storage)
    url = f"/v1/documents/{doc_id}/reclassify"
    req = _signed_request(operator_key, url=url, content_hash="d" * 64)
    audit = _FakeAudit()
    with pytest.raises(ScopeForbidden):
        await documents_reclassify(
            document_id=doc_id,
            body=req,
            request=_request(url),  # type: ignore[arg-type]
            current_user=_current_user(),
            storage=storage,
            audit=audit,  # type: ignore[arg-type]
        )
    assert any(e["payload"].get("rejection_reason") == "no_active_grant" for e in audit.events)


async def test_document_reclassify_demotion_422(storage: BaseRepository, operator_key) -> None:
    _inject_authority(storage, operator_key)
    doc_id = await _put_doc(storage, tier=SensitivityTier.CLASSIFIED)
    url = f"/v1/documents/{doc_id}/reclassify"
    # Sign a valid request that would DEMOTE classified -> restricted.
    req = _signed_request(
        operator_key, url=url, content_hash="d" * 64, new_tier=SensitivityTier.RESTRICTED
    )
    with pytest.raises(UnprocessableError):
        await documents_reclassify(
            document_id=doc_id,
            body=req,
            request=_request(url),  # type: ignore[arg-type]
            current_user=_current_user(),
            storage=storage,
            audit=_FakeAudit(),  # type: ignore[arg-type]
        )
