# SPDX-License-Identifier: AGPL-3.0-or-later
"""FileAccessMixin — signing-key registry + acknowledgment nonces (M9.B1).

Cryptographic FOUNDATION for the file-access journal (API_PLAN §5.6-5.7).
Both tables live in ``audit.db`` so every method uses the AUDIT session
factory (``_audit_session_factory``), not the main one — mirroring how
:class:`AuditMixin` reads the chain.

ANSI SQL only (CLAUDE.md §2.3 Rule 1): the single-use nonce consume is an
atomic compare-and-swap built with generic SQLAlchemy ``update()`` +
``.where()`` — no ``sqlalchemy.dialects.*`` import. This keeps the
race-safe double-spend/expiry rejection in the shared mixin so future
MySQL/Postgres backends inherit it unchanged.

VERIFICATION-side only: no private key at rest, no signing, no byte serving.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlmodel import col, select

from eyenet.models.file_access import (
    FileAccessAcknowledgmentTable,
    SystemUserSigningPubkeyHistoryTable,
)

from ._helpers import safe_session

# §5.6 — acknowledgment nonces are short-lived single-use tokens.
_ACK_TTL = timedelta(seconds=60)


def _fingerprint_of(verifying_key_bytes: bytes) -> str:
    """Fingerprint a raw 32-byte Ed25519 public key.

    Reuses the verification-side primitive so the stored fingerprint is
    byte-identical to the ``kid`` a signer puts on the wire.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
        Ed25519PublicKey,
    )

    from eyenet.crypto import fingerprint  # noqa: PLC0415

    key = Ed25519PublicKey.from_public_bytes(verifying_key_bytes)
    return fingerprint(key)


class FileAccessMixin:
    """Signing-key history + acknowledgment-nonce surface (API_PLAN §5.6-5.7)."""

    async def record_signing_key(
        self,
        user_id: UUID,
        verifying_key_bytes: bytes,
        *,
        now: datetime | None = None,
    ) -> str:
        """Register ``verifying_key_bytes`` as the user's new active key.

        If the user already has an active key (``retired_at IS NULL``), it
        is retired first so there is at most one active key per user. The
        prior key's history row is preserved (signatures from a
        recently-rotated key must still verify). Returns the new key's
        16-hex fingerprint (``kid``).
        """
        set_at = now or datetime.now(tz=UTC)
        fp = _fingerprint_of(verifying_key_bytes)

        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            # Retire any currently-active key for this user.
            retire_stmt = (
                update(SystemUserSigningPubkeyHistoryTable)
                .where(
                    col(SystemUserSigningPubkeyHistoryTable.user_id) == user_id,
                    col(SystemUserSigningPubkeyHistoryTable.retired_at).is_(None),
                )
                .values(retired_at=set_at)
            )
            await session.exec(retire_stmt)

            row = SystemUserSigningPubkeyHistoryTable(
                user_id=user_id,
                verifying_key=verifying_key_bytes,
                fingerprint=fp,
                set_at=set_at,
                retired_at=None,
            )
            session.add(row)
            await session.commit()
        return fp

    async def lookup_key_for_user(
        self,
        user_id: UUID,
        fingerprint: str,
    ) -> tuple[bytes, bool] | None:
        """Resolve THIS user's key (active OR retired) by fingerprint.

        Returns ``(verifying_key_bytes, retired)`` for the row whose
        ``(user_id, fingerprint)`` matches, or ``None`` if that user never
        held a key with this fingerprint. Retired keys resolve so a
        signature minted just before a rotation still verifies.

        The query is bound to the AUTHENTICATED asserting user
        (``WHERE user_id == :uid AND fingerprint == :fp``): a
        non-repudiation journal must never attribute a verification to an
        arbitrary user who happens to share a raw key. The ``(user_id,
        fingerprint)`` UNIQUE constraint guarantees at most one match.
        """
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = select(SystemUserSigningPubkeyHistoryTable).where(
                col(SystemUserSigningPubkeyHistoryTable.user_id) == user_id,
                col(SystemUserSigningPubkeyHistoryTable.fingerprint) == fingerprint,
            )
            result = await session.exec(stmt)
            row = result.first()
            if row is None:
                return None
            return (row.verifying_key, row.retired_at is not None)

    async def active_signing_key_for(self, user_id: UUID) -> bytes | None:
        """Return the user's current active verifying key, or ``None``.

        DETERMINISTIC read: orders ``set_at DESC`` (with ``id`` as a stable
        tiebreak) and takes the newest active row. Even if a transient
        2-active state slipped past the single-active enforcement (the
        SQLite partial-unique index), this resolves to the LATEST key,
        never an arbitrary/older one. Uses ``.first()`` (not ``.one()``) so
        it never crashes on a corrupt multi-active state — fail-safe.
        """
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            stmt = (
                select(SystemUserSigningPubkeyHistoryTable)
                .where(
                    col(SystemUserSigningPubkeyHistoryTable.user_id) == user_id,
                    col(SystemUserSigningPubkeyHistoryTable.retired_at).is_(None),
                )
                .order_by(
                    col(SystemUserSigningPubkeyHistoryTable.set_at).desc(),
                    col(SystemUserSigningPubkeyHistoryTable.id).desc(),
                )
            )
            result = await session.exec(stmt)
            row = result.first()
            return None if row is None else row.verifying_key

    async def record_acknowledgment(
        self,
        user_id: UUID,
        content_hash: str,
        *,
        now: datetime,
    ) -> UUID:
        """Mint a single-use acknowledgment nonce for ``content_hash``.

        Expires at ``now + 60s`` (§5.6). Returns the nonce UUID.
        """
        row = FileAccessAcknowledgmentTable(
            user_id=user_id,
            content_hash=content_hash,
            issued_at=now,
            expires_at=now + _ACK_TTL,
            consumed_at=None,
        )
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row.nonce

    async def consume_acknowledgment(self, nonce: UUID, *, now: datetime) -> bool:
        """Atomically consume a nonce exactly once (§5.6).

        ANSI-generic compare-and-swap (mirrors the Phase-1 candidate CAS):
        ``UPDATE file_access_acknowledgment SET consumed_at=:now
          WHERE nonce=:n AND consumed_at IS NULL AND expires_at > :now``.

        Returns ``True`` iff exactly one row changed — i.e. the nonce
        existed, was unconsumed, and was unexpired. A double-spend (already
        consumed), an expired nonce, and an unknown nonce all return
        ``False``. Atomicity is the single conditional UPDATE: the
        ``consumed_at IS NULL`` predicate guarantees only one concurrent
        caller can win the row.
        """
        stmt = (
            update(FileAccessAcknowledgmentTable)
            .where(
                col(FileAccessAcknowledgmentTable.nonce) == nonce,
                col(FileAccessAcknowledgmentTable.consumed_at).is_(None),
                col(FileAccessAcknowledgmentTable.expires_at) > now,
            )
            .values(consumed_at=now)
        )
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            result = await session.exec(stmt)
            await session.commit()
            return int(result.rowcount) == 1
