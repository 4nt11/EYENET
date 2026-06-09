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

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlmodel import col, select

from eyenet.contracts.enums import FileServedVia, SensitivityTier
from eyenet.crypto import build_journal_row_canonical
from eyenet.models._base import new_uuid7
from eyenet.models.file_access import (
    FileAccessAcknowledgmentTable,
    FileAccessJournalTable,
    SystemUserSigningPubkeyHistoryTable,
)

from ._helpers import safe_session

# §5.6 — acknowledgment nonces are short-lived single-use tokens.
_ACK_TTL = timedelta(seconds=60)

# §5.7 anti-replay — the operator-signed ``sig_timestamp`` must be within this
# window of the server's clock or the request is rejected (stale OR future).
# 300s tolerates clock skew + in-flight latency while still defeating a
# captured-request replay. Overridable per-call via ``record_access``'s
# ``freshness_window`` keyword.
_DEFAULT_FRESHNESS_WINDOW = timedelta(seconds=300)

# Hash-chain genesis seed for the file-access journal: 32 zero bytes. The very
# first journalled access links its ``prev_journal_hash`` to this so a verifier
# recognizes the chain root (mirrors the audit chain's GENESIS_PREV_HASH).
GENESIS_JOURNAL_HASH: bytes = b"\x00" * 32


class FileAccessJournalError(RuntimeError):
    """A file access could not be journalled — recorded fail-closed.

    Raised (never swallowed) when the operator key is unknown, the operator
    signature does not verify, a non-normal access lacks its grant/ack, or the
    acknowledgment nonce is unusable. NO journal row is written in any case.
    """


@dataclass(frozen=True, slots=True)
class _PreparedJournalRow:
    """Fully-validated journal row, ready for the chain-append override.

    Built (and crypto-verified) entirely in the ANSI-generic mixin; the
    dialect-specific override only serializes the single-writer write.
    """

    access_id: UUID
    audit_event_id: UUID | None
    user_id: UUID
    grant_id: UUID | None
    content_hash: bytes
    content_size: int
    content_mime: str
    tier: SensitivityTier
    served_at: datetime
    served_via: FileServedVia
    acknowledgment_id: UUID | None
    operator_signature: bytes
    signing_pubkey_fingerprint: str

    def canonical(self) -> bytes:
        """Injection-proof length-prefixed serialization feeding ``self_hash``.

        DISTINCT from the operator-signed request canonical (that one is
        verified, this one is hashed into the chain) — see
        :func:`eyenet.crypto.build_journal_row_canonical`.
        """

        def _uuid_bytes(value: UUID | None) -> bytes:
            return b"" if value is None else value.bytes

        return build_journal_row_canonical(
            access_id=self.access_id.bytes,
            audit_event_id=_uuid_bytes(self.audit_event_id),
            user_id=self.user_id.bytes,
            grant_id=_uuid_bytes(self.grant_id),
            content_hash=self.content_hash,
            content_size=self.content_size,
            content_mime=self.content_mime,
            tier=self.tier.name,
            served_at=self.served_at.isoformat(),
            served_via=self.served_via.name,
            acknowledgment_id=_uuid_bytes(self.acknowledgment_id),
            operator_signature=self.operator_signature,
            signing_pubkey_fingerprint=self.signing_pubkey_fingerprint,
        )

    def self_hash(self, prev_journal_hash: bytes) -> bytes:
        """``sha256(canonical || prev_journal_hash)`` — the chain link."""
        return hashlib.sha256(self.canonical() + prev_journal_hash).digest()


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

    async def record_access(
        self,
        *,
        user_id: UUID,
        audit_event_id: UUID | None,
        grant_id: UUID | None,
        acknowledgment_id: UUID | None,
        content_hash: bytes,
        content_size: int,
        content_mime: str,
        tier: SensitivityTier,
        served_via: FileServedVia,
        signing_pubkey_fingerprint: str,
        operator_signature: bytes,
        sig_method: str,
        sig_url: str,
        sig_request_id: str,
        sig_timestamp: str,
        sig_body_hash: str,
        now: datetime | None = None,
        freshness_window: timedelta = _DEFAULT_FRESHNESS_WINDOW,
    ) -> UUID:
        """Verify + journal a single file access as a hash-chained row (§5.6).

        FAIL CLOSED at every gate — a :class:`FileAccessJournalError` is raised
        and NO row is written if any check fails:

        a. The operator key is resolved by ``(user_id, fingerprint)``. An
           unknown key cannot verify → raise.
        b. The operator's detached Ed25519 signature is verified against the
           rebuilt ``EYENET-SIG-v1`` request canonical (method/url/request_id/
           timestamp/body_hash/content_hash). This is the CLIENT-signed request
           form — DISTINCT from the journal-row canonical that feeds
           ``self_hash``. An invalid signature → raise.
        b2. FRESHNESS / ANTI-REPLAY: ``sig_timestamp`` (the operator-signed
           ISO-8601 timestamp, now trusted because the signature verified) is
           parsed and compared to ``now``. An unparseable timestamp → raise
           (fail-closed). ``abs(now - sig_timestamp) > freshness_window`` →
           raise (a stale OR future request is rejected). This closes the
           NORMAL-tier replay hole (a captured no-nonce signed request would
           otherwise journal forged rows forever) and is defense-in-depth for
           every tier even once the PHASE-4 HTTP handler also validates it.
           ``freshness_window`` defaults to 300s.
        c. For ``tier != normal`` both ``grant_id`` and ``acknowledgment_id``
           MUST be present (defense in depth above the DB CHECK). The nonce is
           NOT consumed here — consumption is deferred into the serialized
           chain-append transaction (step d) so consume+journal-insert are
           ATOMIC: a failed append leaves the nonce UNCONSUMED (client may
           retry) and writes no row; a successful append consumes the nonce
           exactly once (no double-spend). A used/expired/unknown nonce makes
           the in-transaction conditional UPDATE affect 0 rows → the whole
           transaction rolls back and raises.
        d. Under the audit.db single-writer serialization (``asyncio.Lock`` +
           ``BEGIN IMMEDIATE`` raw-cursor, the SQLite override), the nonce is
           consumed (when required), the prior journal head's ``self_hash`` is
           read (genesis seed if empty), ``self_hash = sha256(canonical_row ||
           prev_journal_hash)`` is computed, the row is INSERTed, and the
           transaction COMMITs — all atomically.

        Returns the new ``access_id``.
        """
        at = now or datetime.now(tz=UTC)

        # (a) Resolve the operator key for THIS user by fingerprint.
        key_row = await self.lookup_key_for_user(user_id, signing_pubkey_fingerprint)
        if key_row is None:
            raise FileAccessJournalError(
                f"no signing key for user {user_id} fingerprint {signing_pubkey_fingerprint}"
            )
        verifying_key_bytes, _retired = key_row

        # (b) Verify the operator-signed request canonical (EYENET-SIG-v1).
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
            Ed25519PublicKey,
        )

        from eyenet.crypto import build_canonical, verify_signature  # noqa: PLC0415

        verifying_key = Ed25519PublicKey.from_public_bytes(verifying_key_bytes)
        canonical = build_canonical(
            sig_method,
            sig_url,
            sig_request_id,
            sig_timestamp,
            sig_body_hash,
            content_hash.hex(),
        )
        if not verify_signature(verifying_key, canonical, operator_signature):
            raise FileAccessJournalError(
                f"operator signature failed verification for user {user_id}"
            )

        # (b2) Freshness / anti-replay. The signature verified, so the signed
        # timestamp is now trustworthy: parse it (fail-closed on garbage) and
        # reject a stale-or-future request outside the window.
        try:
            parsed_ts = datetime.fromisoformat(sig_timestamp)
        except (ValueError, TypeError) as exc:
            raise FileAccessJournalError(
                f"sig_timestamp {sig_timestamp!r} is not parseable ISO-8601"
            ) from exc
        if parsed_ts.tzinfo is None:
            parsed_ts = parsed_ts.replace(tzinfo=UTC)
        if abs(at - parsed_ts) > freshness_window:
            raise FileAccessJournalError(
                f"sig_timestamp {sig_timestamp!r} is outside the freshness window "
                f"of {freshness_window} (now={at.isoformat()})"
            )

        # (c) Tier-conditional grant + acknowledgment presence guard (defense in
        # depth above the DB CHECK). The nonce is consumed ATOMICALLY inside the
        # serialized chain append (step d), NOT here — so a failed append leaves
        # the nonce unconsumed and the client can retry.
        require_nonce = tier is not SensitivityTier.NORMAL
        if require_nonce and (grant_id is None or acknowledgment_id is None):
            raise FileAccessJournalError(
                f"tier {tier.value} access requires both grant_id and "
                f"acknowledgment_id (got grant_id={grant_id}, "
                f"acknowledgment_id={acknowledgment_id})"
            )

        prepared = _PreparedJournalRow(
            access_id=new_uuid7(),
            audit_event_id=audit_event_id,
            user_id=user_id,
            grant_id=grant_id,
            content_hash=content_hash,
            content_size=content_size,
            content_mime=content_mime,
            tier=tier,
            served_at=at,
            served_via=served_via,
            acknowledgment_id=acknowledgment_id,
            operator_signature=operator_signature,
            signing_pubkey_fingerprint=signing_pubkey_fingerprint,
        )

        # (d) Single-writer chain append — dialect-specific override. Consumes
        # the nonce (when ``require_nonce``) in the SAME transaction as the
        # journal INSERT.
        return await self._append_file_access_locked(prepared, require_nonce=require_nonce, now=at)

    async def _append_file_access_locked(  # pragma: no cover — overridden
        self,
        prepared: _PreparedJournalRow,
        *,
        require_nonce: bool,
        now: datetime,
    ) -> UUID:
        """Dialect-specific hash-chained journal append. Subclasses override.

        Mirrors ``_append_audit_locked``: the generic mixin builds + verifies
        the row; the concrete backend serializes the read-head/compute/insert
        under its own single-writer transaction (SQLite: ``BEGIN IMMEDIATE``
        on a raw aiosqlite cursor + an in-process ``asyncio.Lock``).

        CONTRACT (every backend MUST honor): when ``require_nonce`` is true the
        override MUST consume ``prepared.acknowledgment_id`` (conditional
        ``consumed_at IS NULL AND expires_at > now`` compare-and-swap) and
        INSERT the journal row in ONE serialized transaction. If the consume
        affects != 1 row, the whole transaction rolls back and a
        :class:`FileAccessJournalError` is raised — leaving the nonce
        UNCONSUMED (retryable) and writing no row. Consume + journal-insert are
        atomic: never a burned nonce without a row, never a row without a
        consumed nonce (double-spend).
        """
        raise NotImplementedError(
            "_append_file_access_locked is dialect-specific; "
            "the concrete backend repository must override it."
        )

    async def verify_file_access_chain(self) -> bool:
        """Walk the journal in insert order; confirm every chain link (§5.8 prep).

        Recomputes each row's ``self_hash`` from its canonical serialization +
        the prior row's ``self_hash`` (genesis seed for the first row) and
        confirms ``prev_journal_hash`` matches the running head. Returns
        ``False`` on the first broken link (a tampered, reordered, inserted, or
        deleted row), ``True`` for a sound chain. Dialect-agnostic read.
        """
        async with safe_session(self._audit_session_factory) as session:  # type: ignore[attr-defined]
            from sqlalchemy import text  # noqa: PLC0415

            result = await session.exec(select(FileAccessJournalTable).order_by(text("rowid ASC")))
            rows = result.all()

        expected_prev = GENESIS_JOURNAL_HASH
        for row in rows:
            if bytes(row.prev_journal_hash) != expected_prev:
                return False
            prepared = _PreparedJournalRow(
                access_id=row.access_id,
                audit_event_id=row.audit_event_id,
                user_id=row.user_id,
                grant_id=row.grant_id,
                content_hash=bytes(row.content_hash),
                content_size=row.content_size,
                content_mime=row.content_mime,
                tier=row.tier,
                served_at=row.served_at,
                served_via=row.served_via,
                acknowledgment_id=row.acknowledgment_id,
                operator_signature=bytes(row.operator_signature),
                signing_pubkey_fingerprint=row.signing_pubkey_fingerprint,
            )
            if prepared.self_hash(expected_prev) != bytes(row.self_hash):
                return False
            expected_prev = bytes(row.self_hash)
        return True
