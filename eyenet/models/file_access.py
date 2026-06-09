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

from sqlalchemy import Index, LargeBinary, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from ._base import new_uuid7


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


__all__ = [
    "FileAccessAcknowledgmentTable",
    "SystemUserSigningPubkeyHistoryTable",
]
