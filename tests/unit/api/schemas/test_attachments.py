"""Shape tests for §5.6-5.8 file-access schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import (
    FileAccessAcknowledgment,
    FileAccessExoneration,
    FileAccessJournalEntry,
    FileManifest,
    FileServedVia,
    SensitivityTier,
)

pytestmark = pytest.mark.contract

_HASH = "a" * 64
_FP = "b" * 16
_SIG = "ed25519:" + "A" * 88


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def uid() -> UUID:
    return UUID("01906f00-0000-7000-8000-000000000001")


# --- FileManifest -----------------------------------------------------------


def test_file_manifest_happy(uid: UUID, now: datetime) -> None:
    m = FileManifest(
        blob_id=uid,
        content_hash=_HASH,
        content_size=1024,
        content_mime="image/jpeg",
        tier=SensitivityTier.RESTRICTED,
        source_subject_id=uid,
        source_subject_kind="observation",
        collected_at=now,
        access_nonce=uid,
        nonce_expires_at=now,
    )
    assert m.tier is SensitivityTier.RESTRICTED


def test_file_manifest_rejects_bad_hash(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        FileManifest(
            blob_id=uid,
            content_hash="not-hex",
            content_size=0,
            content_mime="x",
            tier=SensitivityTier.NORMAL,
            source_subject_id=uid,
            source_subject_kind="observation",
            collected_at=now,
            access_nonce=uid,
            nonce_expires_at=now,
        )


def test_file_manifest_rejects_extra(uid: UUID, now: datetime) -> None:
    payload = {
        "blob_id": str(uid),
        "content_hash": _HASH,
        "content_size": 0,
        "content_mime": "x",
        "tier": "normal",
        "source_subject_id": str(uid),
        "source_subject_kind": "observation",
        "collected_at": now.isoformat(),
        "access_nonce": str(uid),
        "nonce_expires_at": now.isoformat(),
        "rogue": "x",
    }
    with pytest.raises(PydanticValidationError):
        FileManifest.model_validate(payload)


@pytest.mark.parametrize("kind", ["observation", "message"])
def test_file_manifest_subject_kind(uid: UUID, now: datetime, kind: str) -> None:
    m = FileManifest(
        blob_id=uid,
        content_hash=_HASH,
        content_size=0,
        content_mime="x",
        tier=SensitivityTier.NORMAL,
        source_subject_id=uid,
        source_subject_kind=kind,  # type: ignore[arg-type]
        collected_at=now,
        access_nonce=uid,
        nonce_expires_at=now,
    )
    assert m.source_subject_kind == kind


def test_file_manifest_rejects_bad_subject_kind(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        FileManifest.model_validate(
            {
                "blob_id": str(uid),
                "content_hash": _HASH,
                "content_size": 0,
                "content_mime": "x",
                "tier": "normal",
                "source_subject_id": str(uid),
                "source_subject_kind": "linkage",
                "collected_at": now.isoformat(),
                "access_nonce": str(uid),
                "nonce_expires_at": now.isoformat(),
            }
        )


# --- FileAccessAcknowledgment ----------------------------------------------


def test_acknowledgment_happy(uid: UUID) -> None:
    ack = FileAccessAcknowledgment(
        access_nonce=uid,
        expected_content_hash=_HASH,
        reason="case=APT-29-2026Q2 peer=bob",
        viewing_context="incident=INC-001",
        operator_signature=_SIG,
    )
    assert ack.reason.startswith("case=")


def test_acknowledgment_reason_too_short(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        FileAccessAcknowledgment(
            access_nonce=uid,
            expected_content_hash=_HASH,
            reason="ok",  # too short
            operator_signature=_SIG,
        )


def test_acknowledgment_rejects_bad_signature(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        FileAccessAcknowledgment(
            access_nonce=uid,
            expected_content_hash=_HASH,
            reason="enough characters here",
            operator_signature="rsa:abc",
        )


def test_acknowledgment_rejects_extra(uid: UUID) -> None:
    with pytest.raises(PydanticValidationError):
        FileAccessAcknowledgment.model_validate(
            {
                "access_nonce": str(uid),
                "expected_content_hash": _HASH,
                "reason": "enough characters here",
                "operator_signature": _SIG,
                "rogue": "x",
            }
        )


# --- FileAccessJournalEntry -------------------------------------------------


@pytest.mark.parametrize("via", list(FileServedVia))
def test_journal_entry_every_served_via(uid: UUID, now: datetime, via: FileServedVia) -> None:
    entry = FileAccessJournalEntry(
        access_id=uid,
        audit_event_id=uid,
        user_id=uid,
        content_hash=_HASH,
        content_size=0,
        tier=SensitivityTier.NORMAL,
        served_at=now,
        served_via=via,
        operator_signature_verified=True,
        signing_pubkey_fingerprint=_FP,
    )
    assert entry.served_via is via


@pytest.mark.parametrize("tier", list(SensitivityTier))
def test_journal_entry_every_tier(uid: UUID, now: datetime, tier: SensitivityTier) -> None:
    entry = FileAccessJournalEntry(
        access_id=uid,
        audit_event_id=uid,
        user_id=uid,
        content_hash=_HASH,
        content_size=0,
        tier=tier,
        served_at=now,
        served_via=FileServedVia.ATTACHMENT_STREAM,
        operator_signature_verified=True,
        signing_pubkey_fingerprint=_FP,
    )
    assert entry.tier is tier


def test_journal_entry_rejects_bad_fingerprint(uid: UUID, now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        FileAccessJournalEntry(
            access_id=uid,
            audit_event_id=uid,
            user_id=uid,
            content_hash=_HASH,
            content_size=0,
            tier=SensitivityTier.NORMAL,
            served_at=now,
            served_via=FileServedVia.INLINE_JSON,
            operator_signature_verified=True,
            signing_pubkey_fingerprint="too-short",
        )


# --- FileAccessExoneration --------------------------------------------------


def test_exoneration_empty_accesses_is_valid(now: datetime) -> None:
    """Empty accesses IS the load-bearing exoneration proof."""
    ex = FileAccessExoneration(
        content_hash=_HASH,
        query_time=now,
        journal_head_at_query=_HASH,
        accesses=[],
        exoneration_signature=_SIG,
    )
    assert ex.accesses == []


def test_exoneration_with_accesses(uid: UUID, now: datetime) -> None:
    entry = FileAccessJournalEntry(
        access_id=uid,
        audit_event_id=uid,
        user_id=uid,
        content_hash=_HASH,
        content_size=0,
        tier=SensitivityTier.RESTRICTED,
        served_at=now,
        served_via=FileServedVia.ATTACHMENT_STREAM,
        operator_signature_verified=True,
        signing_pubkey_fingerprint=_FP,
    )
    ex = FileAccessExoneration(
        content_hash=_HASH,
        query_time=now,
        journal_head_at_query=_HASH,
        accesses=[entry],
        exoneration_signature=_SIG,
    )
    assert len(ex.accesses) == 1
    assert ex.accesses[0].access_id == uid


def test_exoneration_rejects_extra(now: datetime) -> None:
    with pytest.raises(PydanticValidationError):
        FileAccessExoneration.model_validate(
            {
                "content_hash": _HASH,
                "query_time": now.isoformat(),
                "journal_head_at_query": _HASH,
                "accesses": [],
                "exoneration_signature": _SIG,
                "rogue": "x",
            }
        )
