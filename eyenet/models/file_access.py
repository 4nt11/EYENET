# SPDX-License-Identifier: AGPL-3.0-or-later
"""File-access cryptographic foundation tables (API_PLAN §5.6-5.7, M9.B1).

Both tables physically live in ``audit.db`` (co-located with ``audit_log``
per §5.5 — the tamper-evidence durability gate). Routing is decided by
``_AUDIT_TABLES`` in :mod:`eyenet.storage.sqlite_repo.database`, NOT here:
this layer only registers the classes on the shared ``SQLModel.metadata``.

This is the VERIFICATION-side foundation only — no private key at rest, no
byte-serving, no journal row. Those are B2/B3.

``SystemUserSigningPubkeyHistoryTable`` — the operator pubkey rotation
trail (§5.7). Every historical pubkey is preserved so journal rows signed
by a recently-retired key still verify, and an insider who rotates the
pubkey before forging signatures is defeated (the history pins which key
authorized which access).

``FileAccessAcknowledgmentTable`` — single-use, short-lived nonce (§5.6).
The two-step file-access flow mints a nonce, the operator acknowledges the
``content_hash`` it is about to read, and the consume step is an atomic
compare-and-swap so a double-spend or an expired nonce is rejected
race-safely.

ANSI SQL column types only (CLAUDE.md §2.3 Rule 1) — no dialect-specific
types so future MySQL/Postgres backends bind the same classes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, LargeBinary, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from eyenet.contracts.enums import FileServedVia, SensitivityTier

from ._base import new_uuid7

# Tier-conditional integrity (API_PLAN §5.6). A non-``normal`` access MUST
# carry both a clearance grant and a consumed acknowledgment nonce. Expressed
# as a DB-level CHECK so the invariant holds even on a raw INSERT that bypasses
# the application path (defense in depth above ``record_access``'s typed
# guard). SQLModel persists a StrEnum by its NAME (uppercase) — the stored
# value is ``'NORMAL'`` / ``'RESTRICTED'`` / ``'CLASSIFIED'`` — so the CHECK
# compares against the uppercase name, NOT the lowercase StrEnum value.
# ANSI-portable (plain CheckConstraint, no dialect SQL) per CLAUDE.md §2.3.
_TIER_REQUIRES_GRANT_AND_ACK_CK = (
    "tier = 'NORMAL' OR (grant_id IS NOT NULL AND acknowledgment_id IS NOT NULL)"
)


class SystemUserSigningPubkeyHistoryTable(SQLModel, table=True):
    """Operator Ed25519 verifying-key rotation trail (API_PLAN §5.7).

    Exactly one row per user has ``retired_at IS NULL`` — the current
    active key. Rotation retires the prior row (sets ``retired_at``) and
    inserts a new active row. Retired rows are NEVER deleted: a signature
    produced by a recently-rotated key must still verify.
    """

    __tablename__ = "system_user_signing_pubkey_history"
    __table_args__ = (
        # A user must never hold two history rows with the same fingerprint:
        # verification resolves a key by ``(user_id, fingerprint)`` and that
        # tuple must be unambiguous. ANSI-portable composite UNIQUE (Rule 1) —
        # binds identically on future MySQL/Postgres backends. This also backs
        # the user-scoped fingerprint resolver lookup.
        UniqueConstraint("user_id", "fingerprint", name="uq_signing_pubkey_user_fp"),
    )

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference to ``system_user`` (in main.db) — no FK across
    # physical files, mirroring the clearance-grant convention.
    user_id: UUID = Field(index=True)
    # Raw 32-byte Ed25519 public key. Stored as bytes (BLOB) — ANSI-generic
    # via SQLAlchemy ``LargeBinary``.
    verifying_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    # First 8 bytes of sha256(DER SubjectPublicKeyInfo) hex-encoded = 16 chars.
    # This is the ``kid`` carried on the wire (§5.7 header).
    fingerprint: str = Field(max_length=16)
    set_at: datetime
    # ``None`` == current active key. Set on rotation.
    retired_at: datetime | None = None


class FileAccessAcknowledgmentTable(SQLModel, table=True):
    """Single-use file-access acknowledgment nonce (API_PLAN §5.6).

    Minted with a 60-second lifetime; consumed atomically exactly once.
    Consumption is a conditional UPDATE (``consumed_at IS NULL AND
    expires_at > now``) so a double-spend and an expired-nonce use are
    rejected race-safely in the database, not in application logic.
    """

    __tablename__ = "file_access_acknowledgment"
    __table_args__ = (
        # Operator-history lookup: "what did user X acknowledge, when?"
        Index("ix_file_ack_user_issued", "user_id", "issued_at"),
    )

    nonce: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference to ``system_user`` (main.db) — no FK.
    user_id: UUID = Field(index=True)
    # sha256 hex (64 chars) of the blob being acknowledged.
    content_hash: str = Field(max_length=64)
    issued_at: datetime
    expires_at: datetime
    # ``None`` == not yet consumed.
    consumed_at: datetime | None = None


class FileAccessJournalTable(SQLModel, table=True):
    """Hash-chained, signature-bearing file-access journal (API_PLAN §5.6, M9.B2).

    A SECOND tamper-evident chain (physically co-located with ``audit_log`` in
    ``audit.db``), mirroring the audit hash-chain EXACTLY: every row carries
    ``prev_journal_hash`` (the prior row's ``self_hash``; the genesis row links
    to the all-zero seed) and ``self_hash`` (sha256 over an injection-proof
    length-prefixed framing of this row's identity fields, concatenated with
    ``prev_journal_hash``). The single-writer ``BEGIN IMMEDIATE`` append path
    lives in the SQLite backend override (``record_access``).

    ``operator_signature`` is MANDATORY on every row — the non-repudiation
    anchor. The signature is verified against the operator's registered
    verifying key (resolved by ``signing_pubkey_fingerprint``) BEFORE the row
    is written; an unverifiable access is never journalled (fail closed).

    ``content_hash`` is the exoneration key (indexed): "prove who accessed the
    blob with this hash, and that nothing else was served under it."
    """

    __tablename__ = "file_access_journal"
    __table_args__ = (
        # Exoneration lookups pivot on the served blob's content hash.
        Index("ix_file_access_journal_content_hash", "content_hash"),
        CheckConstraint(
            _TIER_REQUIRES_GRANT_AND_ACK_CK,
            name="ck_file_access_journal_tier_requires_grant_ack",
        ),
    )

    access_id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    # Cross-store reference to the ``audit_log`` row this access also emitted
    # (main.db audit chain). Nullable for now — no FK across physical stores
    # (mirrors the clearance-grant / signing-key cross-store convention).
    audit_event_id: UUID | None = None
    # Cross-store reference to ``system_user`` (main.db) — no FK.
    user_id: UUID = Field(index=True)
    # Clearance grant that authorized a non-normal access (§4.8). MUST be
    # present for tier != normal (enforced by the CHECK above + typed guard).
    grant_id: UUID | None = None
    # 32-byte sha256 of the served bytes — the exoneration key.
    content_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    content_size: int
    content_mime: str
    tier: SensitivityTier
    served_at: datetime
    served_via: FileServedVia
    # Consumed acknowledgment nonce. MUST be present for tier != normal.
    acknowledgment_id: UUID | None = None
    # Detached Ed25519 operator signature over the EYENET-SIG-v1 canonical
    # request form (§5.7). MANDATORY every row.
    operator_signature: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    # 16-hex kid of the verifying key that authorized this access (§5.7).
    signing_pubkey_fingerprint: str = Field(max_length=16)
    # Hash-chain linkage: 32-byte digests (genesis = 32 zero bytes).
    prev_journal_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    self_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))


__all__ = [
    "FileAccessAcknowledgmentTable",
    "FileAccessJournalTable",
    "SystemUserSigningPubkeyHistoryTable",
]
