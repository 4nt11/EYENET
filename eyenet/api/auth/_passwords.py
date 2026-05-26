# SPDX-License-Identifier: AGPL-3.0-or-later
"""argon2id password hashing — the single source for the cost profile.

Profile lives here (not in handler code) so A3 (MFA enrollment) and A6
(reset-mfa CLI) reuse the same params. Cost is the
``argon2.PasswordHasher`` library default (``time_cost=3,
memory_cost=64MiB, parallelism=4``) — OWASP-recommended floor as of
2026. Heavier-is-better ([[feedback_crypto_heavier_is_better]]) applies
to RSA where the operational impact is sub-millisecond per request;
argon2 cost lands on every login synchronously, so the OWASP floor is
the right default until calibrated otherwise.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    """Return the argon2id PHC-format hash string for ``plaintext``."""
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """Constant-time-ish argon2 verify. False on mismatch; raises on a
    structurally bad ``stored_hash``."""
    try:
        return _hasher.verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


__all__ = ["hash_password", "verify_password"]
