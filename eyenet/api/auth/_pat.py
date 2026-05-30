# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal Access Token minting + at-rest hashing (M9.A4).

Format: ``eyenet_pat_<22-char-prefix>_<32-char-secret>`` (API_PLAN §4.3).

The 32-char secret carries ~190 bits of entropy. Hash-at-rest is
HMAC-SHA256 keyed with a server-side pepper (``<data_dir>/jwt/pat_pepper``,
mode 0600) — NOT argon2id. Two reasons:

1. The PAT is presented as a bearer on EVERY request (Prometheus scrapes
   the metrics endpoint every few seconds). argon2id's per-row random salt
   forbids an indexed equality lookup, forcing a per-request slow hash;
   a deterministic keyed digest is an index seek.
2. [[feedback_crypto_heavier_is_better]] — "pick the heavier parameter
   set" applies where the secret is low-entropy / guessable (passwords,
   key sizes). A 190-bit random token is not brute-forceable regardless of
   hash speed; the pepper is what defends against DB exfiltration. Whoever
   holds ``main.db`` but not ``pat_pepper`` learns nothing.

Parsing is by fixed offset, never ``str.split('_')`` — the URL-safe base64
alphabet of :func:`secrets.token_urlsafe` includes ``_``, so a naive split
would corrupt prefixes/secrets that happen to contain the separator char.
"""

from __future__ import annotations

import hmac
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Final

_TOKEN_PREFIX: Final[str] = "eyenet_pat_"
_PREFIX_LEN: Final[int] = 22
_SECRET_LEN: Final[int] = 32
_PEPPER_NAME: Final[str] = "pat_pepper"
_PEPPER_BYTES: Final[int] = 32


def _rand(length: int) -> str:
    """Return ``length`` URL-safe ASCII chars of CSPRNG output."""
    # token_urlsafe(n) yields ~1.3n chars; over-generate then slice to the
    # exact width. Every char stays in the URL-safe base64 alphabet.
    return secrets.token_urlsafe(length * 2)[:length]


def hash_pat(pepper: bytes, secret: str) -> str:
    """Return ``HMAC_SHA256(pepper, secret)`` as a 64-char hex digest.

    Deterministic — the storage column is UNIQUE-indexed on this value so
    the auth-time lookup is a single index seek.
    """
    return hmac.new(pepper, secret.encode("utf-8"), sha256).hexdigest()


def mint_pat(pepper: bytes) -> tuple[str, str, str]:
    """Mint a fresh PAT. Returns ``(full_token, prefix, hash_hex)``.

    ``full_token`` is shown to the operator exactly ONCE; ``prefix`` is
    stored plaintext for display + auth-time match; ``hash_hex`` is the
    only secret-derived value persisted.
    """
    prefix = _rand(_PREFIX_LEN)
    secret = _rand(_SECRET_LEN)
    full_token = f"{_TOKEN_PREFIX}{prefix}_{secret}"
    return full_token, prefix, hash_pat(pepper, secret)


def parse_pat(token: str) -> tuple[str, str] | None:
    """Split a presented PAT into ``(prefix, secret)`` or ``None`` if malformed.

    Fixed-offset parse: after the ``eyenet_pat_`` literal, the body is
    exactly ``<22-char-prefix>`` + ``_`` + ``<32-char-secret>``.
    """
    if not token.startswith(_TOKEN_PREFIX):
        return None
    body = token[len(_TOKEN_PREFIX) :]
    if len(body) != _PREFIX_LEN + 1 + _SECRET_LEN:
        return None
    if body[_PREFIX_LEN] != "_":
        return None
    return body[:_PREFIX_LEN], body[_PREFIX_LEN + 1 :]


def is_pat(token: str) -> bool:
    """True if ``token`` carries the PAT prefix (cheap pre-parse triage)."""
    return token.startswith(_TOKEN_PREFIX)


def load_pat_pepper(data_dir: Path) -> bytes:
    """Return the HMAC pepper, materializing it on first call.

    ``<data_dir>/jwt/pat_pepper`` (mode 0600), alongside the JWT signing
    keypair and the MFA Fernet key — same boot path, same operator backup
    story (``development/MFA_OPS.md``). Losing this file invalidates every
    PAT (they become unverifiable); operators re-mint.
    """
    jwt_dir = data_dir / "jwt"
    jwt_dir.mkdir(parents=True, exist_ok=True)
    pepper_path = jwt_dir / _PEPPER_NAME
    if not pepper_path.exists():
        pepper_path.write_bytes(secrets.token_bytes(_PEPPER_BYTES))
        pepper_path.chmod(0o600)
    return pepper_path.read_bytes()


__all__ = [
    "hash_pat",
    "is_pat",
    "load_pat_pepper",
    "mint_pat",
    "parse_pat",
]
