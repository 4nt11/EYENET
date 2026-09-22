"""File-access surfaces — API_PLAN §5.6 (journal), §5.7 (signatures), §5.8 (exoneration).

These schemas implement the non-repudiation contract:

- `FileManifest` is the safe metadata-only envelope returned by step 1 of the
  two-step access flow. Calling it appends NO journal row.
- `FileAccessAcknowledgment` is the signed body POSTed in step 2; only after
  the server verifies the operator signature and clearance scope do bytes flow
  and a `file_access_journal` row get appended.
- `FileAccessJournalEntry` mirrors a single row of `file_access_journal`.
- `FileAccessExoneration` is the server-signed envelope returned by
  `/v1/audit/file-access`. Empty `accesses` is a positive cryptographic
  assertion of non-access.

Operator signatures are transmitted as a single string with the canonical form
`ed25519:<base64sig>` (urlsafe base64, padded). The 86-90-char range covers
the standard 88-char Ed25519 signature plus optional padding edge cases.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import FileServedVia, SensitivityTier
from .pagination import CursorPage

if TYPE_CHECKING:
    from eyenet.contracts.message import AttachmentRow

_HEX_64 = r"^[0-9a-f]{64}$"
_HEX_16 = r"^[0-9a-f]{16}$"
_ED25519_SIG = r"^ed25519:[A-Za-z0-9_\-]{86,90}={0,2}$"


class FileManifest(ApiSchema):
    """Metadata envelope — step 1 of §5.6 two-step access flow. NO content bytes."""

    blob_id: UUID
    content_hash: str = Field(pattern=_HEX_64, description="SHA-256 of the stored bytes, hex.")
    content_size: int = Field(ge=0)
    content_mime: str = Field(max_length=128)
    tier: SensitivityTier
    source_subject_id: UUID
    source_subject_kind: Literal["observation", "message"]
    collected_at: datetime
    access_nonce: UUID = Field(description="Single-use, 60s TTL, required for step 2.")
    nonce_expires_at: datetime


class AttachmentSummary(ApiSchema):
    """Projection of an AttachmentRow for the list surface (``GET /v1/attachments``).

    Metadata only. ``tier`` is the effective sensitivity (``operator_tier_override``
    over ``classifier_tier``); ``classifier_tier`` is surfaced too for a promotion
    badge. ``source_subject_*``/``collected_at`` are manifest-only (they need the
    parent-message join), so they are not on the list row.
    """

    blob_id: UUID
    message_id: UUID
    kind: str = Field(max_length=64)
    mime: str = Field(max_length=128)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_HEX_64, description="SHA-256 of the stored bytes, hex.")
    filename: str | None = None
    classifier_tier: SensitivityTier
    tier: SensitivityTier = Field(description="Effective tier = override or classifier.")

    @classmethod
    def from_domain(cls, row: AttachmentRow) -> AttachmentSummary:
        return cls(
            blob_id=row.id,
            message_id=row.message_id,
            kind=str(row.kind),
            mime=row.mime,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            filename=row.filename,
            classifier_tier=row.classifier_tier,
            tier=row.operator_tier_override or row.classifier_tier,
        )


class FileAccessAcknowledgment(ApiSchema):
    """Signed body POSTed in step 2 of §5.6.

    `operator_signature` is computed over the §5.7 canonical request form
    (`EYENET-SIG-v1` envelope). The server reconstructs the canonical form
    from the request and verifies against `system_user.signing_pubkey`.
    """

    access_nonce: UUID
    expected_content_hash: str = Field(pattern=_HEX_64)
    request_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Client-chosen opaque request identifier, signed into the §5.7 "
            "canonical. Anti-replay residual until PHASE-6 adds "
            "UNIQUE(user_id, sig_request_id)."
        ),
    )
    signed_at: datetime = Field(
        description=(
            "Operator-signed ISO-8601 timestamp. record_access rejects a "
            "stale OR future value outside the freshness window (§5.7)."
        ),
    )
    reason: str = Field(
        min_length=16,
        max_length=1024,
        description="Mandatory justification. 'ok' is not a reason.",
    )
    viewing_context: str | None = Field(
        default=None,
        max_length=512,
        description="Free-text case/incident reference (e.g. 'case=APT-29-2026Q2').",
    )
    operator_signature: str = Field(
        pattern=_ED25519_SIG,
        description="Ed25519 signature over the canonical EYENET-SIG-v1 form.",
    )
    case_refs: list[UUID] = Field(
        default_factory=list,
        max_length=32,
        description=(
            "Cases the operator is working under for this access (§4.10.7). "
            "Server REQUIRES at least one entry resolving to a case where the "
            "target row is a member AND the caller is a collaborator when the "
            "row's effective tier is `classified` (§4.10.4 hybrid rule)."
        ),
    )


class FileAccessJournalEntry(ApiSchema):
    """One row of `file_access_journal` (§5.6)."""

    access_id: UUID
    audit_event_id: UUID | None = Field(
        default=None,
        description="FK to audit_log_event.id (§5.5 hash chain); null when unlinked.",
    )
    user_id: UUID
    grant_id: UUID | None = Field(
        default=None,
        description="Authorizing clearance grant; mandatory when `tier != normal`.",
    )
    content_hash: str = Field(pattern=_HEX_64)
    content_size: int = Field(ge=0)
    content_mime: str | None = Field(default=None, max_length=128)
    tier: SensitivityTier
    served_at: datetime
    served_via: FileServedVia
    operator_signature_verified: bool
    signing_pubkey_fingerprint: str = Field(
        pattern=_HEX_16,
        description="sha256(operator verifying-key DER)[:8] — disambiguates key version.",
    )


class FileAccessExoneration(ApiSchema):
    """Server-signed assertion against the journal head — §5.8.

    Empty `accesses` is a positive cryptographic statement of non-access at
    `query_time` for the journal at head `journal_head_at_query`. Combined
    with externally-anchored heads (§5.9), independently verifiable.
    """

    content_hash: str = Field(
        pattern=_HEX_64,
        description=(
            "The hash being attested. For by-user queries this carries the "
            "sentinel value defined in the canonical-form contract."
        ),
    )
    query_time: datetime
    journal_head_at_query: str = Field(
        pattern=_HEX_64,
        description="`self_hash` of the latest `file_access_journal` row at query time.",
    )
    accesses: list[FileAccessJournalEntry] = Field(default_factory=list)
    exoneration_signature: str = Field(
        pattern=_ED25519_SIG,
        description="Ed25519 server signature over EYENET-EXONERATION-v1 canonical form.",
    )


class CursorPageAttachmentSummary(CursorPage[AttachmentSummary]):
    """200 page response for ``GET /v1/attachments``."""


__all__ = [
    "AttachmentSummary",
    "CursorPageAttachmentSummary",
    "FileAccessAcknowledgment",
    "FileAccessExoneration",
    "FileAccessJournalEntry",
    "FileManifest",
]
