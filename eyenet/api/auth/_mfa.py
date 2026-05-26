# SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: RUF002 — Unicode digit examples are intentional in docstrings
"""TOTP helpers (RFC 6238) — M9.A3.

Thin :mod:`pyotp` wrapper. Defaults: SHA-1 HMAC, 30-second step, 6 digits
(the only combination provisioned by every authenticator app in the wild).

Note for future readers: enroll / verify-enroll / disable handlers DO NOT
invalidate the A2 auth cache. MFA writes touch ``mfa_secret_encrypted`` on
the credential row, which is NOT part of the cached ``AuthContext``
(user / role / explicit scopes / clearance grants). Keep that contract
intact — don't add defensive ``cache.invalidate(...)`` calls.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Final

import pyotp

# Single source of truth for the TOTP parameters. Keep these constants —
# changing them silently invalidates every enrolled user's authenticator.
_SECRET_BYTES: Final[int] = 20  # → 32 base32 chars; RFC 4226 recommended floor
_DIGITS: Final[int] = 6
_STEP_SECONDS: Final[int] = 30
_TOLERANCE_STEPS: Final[int] = 1  # ±1 step per RFC 6238 §5.2

ISSUER: Final[str] = "eyenet"


def generate_secret() -> str:
    """Mint a fresh base32-encoded TOTP secret (160 bits / 32 chars)."""
    raw = secrets.token_bytes(_SECRET_BYTES)
    # pyotp.random_base32 uses os.urandom under the hood; we route through
    # `secrets` directly so static analyzers can't flag this as weak.
    import base64  # noqa: PLC0415 — local to keep top-level imports tight

    return base64.b32encode(raw).decode("ascii").rstrip("=")


def provisioning_uri(*, secret_b32: str, username: str, issuer: str = ISSUER) -> str:
    """Return the ``otpauth://`` URI used by clients to render the QR code."""
    return pyotp.TOTP(secret_b32, digits=_DIGITS, interval=_STEP_SECONDS).provisioning_uri(
        name=username,
        issuer_name=issuer,
    )


def verify_code(*, secret_b32: str, code: str, now: datetime) -> bool:
    """Verify a 6-digit TOTP against ``secret_b32`` at ``now`` with ±1 step tolerance.

    Gate is ASCII-only on the digit set: ``str.isdigit`` alone returns
    ``True`` for Unicode digit categories (Arabic-Indic ``٠١٢٣٤٥``,
    Devanagari ``१२३४५६``, mathematical bold ``𝟏𝟐𝟑𝟒𝟓𝟔``), so we pair it
    with :py:meth:`str.isascii` to clamp to plain `0`–`9`. Defense in
    depth behind the schema regex; pyotp's own equality would also
    reject exotic inputs but the explicit gate keeps the failure shape
    predictable for direct callers (CLI, future internal code).
    """
    if len(code) != _DIGITS:
        return False
    if not (code.isascii() and code.isdigit()):
        return False
    totp = pyotp.TOTP(secret_b32, digits=_DIGITS, interval=_STEP_SECONDS)
    return bool(totp.verify(code, for_time=now, valid_window=_TOLERANCE_STEPS))


__all__ = [
    "ISSUER",
    "generate_secret",
    "provisioning_uri",
    "verify_code",
]
