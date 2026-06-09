# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator signing-key registration logic (PHASE-4 — proof-of-possession).

Self-service ONLY: an authenticated operator enrolls THEIR OWN Ed25519
verifying key, proving possession of the matching private key by signing a
short-lived server-minted challenge. There is no admin-override path.

This module is the PURE verification seam: :func:`register_operator_signing_key`
is a focused async function taking the repository + the submitted material and
returning the new key's fingerprint, raising :class:`SigningKeyRegistrationError`
(fail closed) at every gate. The HTTP handler is a thin wrapper that maps the
typed failures to status codes; the security-critical ordering and checks live
here so they are unit-testable without an ASGI client.

Ordering — verify PoP THEN consume the nonce:
    1. Load the SUBMITTED public key (malformed → raise, register nothing).
    2. Verify the proof-of-possession signature AGAINST the submitted key
       (it is not registered yet, so it cannot be looked up). The canonical
       binds BOTH the nonce and the public key, so a captured proof cannot be
       re-presented under a swapped key.
    3. Atomically consume the user-bound, single-use challenge nonce. This is
       the anti-replay COMMIT point.
    4. Record the key (rotating/retiring any prior active key via B1).

Verifying before consuming is deliberate: an Ed25519 proof is not
brute-forceable, so permitting an honest client to retry the SAME challenge
within its 60s TTL (e.g. a dropped response) is harmless and better UX. The
atomic single-use consume — not the verify — is what defeats replay: once the
nonce is consumed, no further registration can ride it. Consuming first would
burn the nonce on every malformed-signature attempt and force a fresh
challenge round-trip for a benign retry, with no security gain.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from eyenet.crypto import (
    build_signing_key_challenge_canonical,
    load_ed25519_public_key,
    verify_signature,
)
from eyenet.storage.repository import BaseRepository


class SigningKeyRegistrationError(RuntimeError):
    """Registration failed — fail closed, NO key recorded, NO nonce burned
    unless the atomic consume itself succeeded.

    ``reason`` is a short stable code for audit/logging; it is intentionally
    NOT echoed verbatim to the client (the handler maps to a generic 4xx) to
    avoid an enumeration oracle on this authentication boundary.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def register_operator_signing_key(
    storage: BaseRepository,
    *,
    user_id: UUID,
    public_key_bytes: bytes,
    challenge_nonce: UUID,
    challenge_signature: bytes,
    now: datetime,
) -> str:
    """Verify proof-of-possession and register ``public_key_bytes`` for ``user_id``.

    Returns the new key's 16-hex fingerprint (``kid``). Raises
    :class:`SigningKeyRegistrationError` (register nothing) on a malformed key,
    a failed proof, or an unusable challenge nonce.
    """
    # (a) Load the SUBMITTED key. Malformed / wrong-length / backend-rejected
    #     bytes fail closed without crashing on attacker-controlled input.
    public_key = load_ed25519_public_key(public_key_bytes)
    if public_key is None:
        raise SigningKeyRegistrationError("malformed_public_key")

    # (b) Verify proof-of-possession AGAINST the submitted key. The canonical
    #     binds the nonce AND the public key, so a MITM cannot swap the key
    #     under a captured-valid signature. ``verify_signature`` returns False
    #     (never raises) on a non-bytes / wrong-length / mismatched signature.
    canonical = build_signing_key_challenge_canonical(str(challenge_nonce), public_key_bytes)
    if not verify_signature(public_key, canonical, challenge_signature):
        raise SigningKeyRegistrationError("proof_of_possession_failed")

    # (c) Atomically consume the user-bound, single-use challenge. This is the
    #     anti-replay commit point: a replayed / expired / unknown / wrong-user
    #     nonce flips zero rows → False → raise, register nothing.
    consumed = await storage.consume_signing_key_challenge(challenge_nonce, user_id, now=now)
    if not consumed:
        raise SigningKeyRegistrationError("challenge_unusable")

    # (d) Record the key — rotates/retires any prior active key (B1 invariant).
    return await storage.record_signing_key(user_id, public_key_bytes, now=now)


__all__ = ["SigningKeyRegistrationError", "register_operator_signing_key"]
