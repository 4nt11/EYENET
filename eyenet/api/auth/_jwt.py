# SPDX-License-Identifier: AGPL-3.0-or-later
"""RS256 JWT sign/verify + refresh-secret minting.

API_PLAN §4.2 — JWT shape is identity-only (sub, jti, iat, exp). Role and
scopes are NEVER carried in claims; storage is authoritative
([[project_clearance_model]]).

Key choice: RSA-4096. Operator-grade forensic evidence
([[feedback_crypto_heavier_is_better]]) — court-defensibility outweighs
the per-request verify cost.

Keypair on disk: ``<data_dir>/jwt/signing_key.pem`` (private, 0600) and
one-or-more ``verifying_key*.pem`` (public). Loader supports N verifying
keys keyed by ``kid`` so rotation lands without a code change. ``kid`` is
``sha256(verifying_key_pem)[:16]``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from eyenet.models._base import new_uuid7

ALGORITHM: Final[str] = "RS256"
ISSUER: Final[str] = "eyenet"
ACCESS_TTL: Final[timedelta] = timedelta(minutes=15)
REFRESH_TTL: Final[timedelta] = timedelta(days=30)
_RSA_KEY_BITS: Final[int] = 4096

_SIGNING_KEY_NAME = "signing_key.pem"
_VERIFYING_KEY_NAME = "verifying_key.pem"
_VERIFYING_KEY_GLOB = "verifying_key*.pem"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_pem: bytes


@dataclass(frozen=True)
class VerifyingKey:
    kid: str
    public_pem: bytes


@dataclass(frozen=True)
class AccessClaims:
    """Decoded JWT body — identity only, never authority."""

    user_id: UUID
    jti: UUID
    issued_at: datetime
    expires_at: datetime


class JwtError(Exception):
    """Internal — the public 401 surface is `AuthError` in deps.py."""


def _kid_for(public_pem: bytes) -> str:
    return hashlib.sha256(public_pem).hexdigest()[:16]


def _ensure_jwt_dir(jwt_dir: Path) -> Path:
    jwt_dir.mkdir(parents=True, exist_ok=True)
    return jwt_dir


def _write_pem(path: Path, content: bytes, mode: int) -> None:
    path.write_bytes(content)
    path.chmod(mode)


def _generate_keypair(jwt_dir: Path) -> tuple[Path, Path]:
    """Mint a fresh RSA-4096 keypair under ``jwt_dir``. PEM, 0600/0644."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=_RSA_KEY_BITS)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signing_path = jwt_dir / _SIGNING_KEY_NAME
    verifying_path = jwt_dir / _VERIFYING_KEY_NAME
    _write_pem(signing_path, private_pem, 0o600)
    _write_pem(verifying_path, public_pem, 0o644)
    return signing_path, verifying_path


def load_signing_keypair(data_dir: Path) -> SigningKey:
    """Return the current signing key, materializing the dir on first call."""
    jwt_dir = _ensure_jwt_dir(data_dir / "jwt")
    signing_path = jwt_dir / _SIGNING_KEY_NAME
    verifying_path = jwt_dir / _VERIFYING_KEY_NAME
    if not signing_path.exists() or not verifying_path.exists():
        _generate_keypair(jwt_dir)
    private_pem = signing_path.read_bytes()
    public_pem = verifying_path.read_bytes()
    return SigningKey(kid=_kid_for(public_pem), private_pem=private_pem)


def load_verifying_keys(data_dir: Path) -> dict[str, VerifyingKey]:
    """Return every verifying key in ``<data_dir>/jwt`` keyed by ``kid``.

    Rotation drops a second ``verifying_key.<kid>.pem`` alongside the
    primary — this loader picks them all up automatically.
    """
    jwt_dir = _ensure_jwt_dir(data_dir / "jwt")
    primary = jwt_dir / _VERIFYING_KEY_NAME
    if not primary.exists():
        _generate_keypair(jwt_dir)
    out: dict[str, VerifyingKey] = {}
    for path in jwt_dir.glob(_VERIFYING_KEY_GLOB):
        pem = path.read_bytes()
        kid = _kid_for(pem)
        out[kid] = VerifyingKey(kid=kid, public_pem=pem)
    return out


def mint_access_token(
    *,
    user_id: UUID,
    signing_key: SigningKey,
    now: datetime | None = None,
) -> tuple[str, AccessClaims]:
    """Sign one access token. ``jti`` is a fresh UUID7 (chronologically sortable)."""
    moment = now or datetime.now(tz=UTC)
    jti = UUID(str(new_uuid7()))
    expires_at = moment + ACCESS_TTL
    payload = {
        "iss": ISSUER,
        "sub": str(user_id),
        "jti": str(jti),
        "iat": int(moment.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        payload,
        signing_key.private_pem,
        algorithm=ALGORITHM,
        headers={"kid": signing_key.kid},
    )
    claims = AccessClaims(
        user_id=user_id,
        jti=jti,
        issued_at=moment,
        expires_at=expires_at,
    )
    return token, claims


def decode_access_token(
    token: str,
    *,
    verifying_keys: dict[str, VerifyingKey],
) -> AccessClaims:
    """Verify signature + standard claims; return parsed identity.

    Raises :class:`JwtError` for every failure mode (expired, bad
    signature, kid unknown, malformed).
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.exceptions.PyJWTError as exc:
        raise JwtError("malformed_token") from exc
    kid = header.get("kid")
    if not isinstance(kid, str) or kid not in verifying_keys:
        raise JwtError("unknown_kid")
    vkey = verifying_keys[kid]
    try:
        payload = jwt.decode(
            token,
            vkey.public_pem,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise JwtError("expired_token") from exc
    except jwt.InvalidTokenError as exc:
        raise JwtError("invalid_token") from exc
    try:
        user_id = UUID(payload["sub"])
        jti = UUID(payload["jti"])
    except (KeyError, ValueError, TypeError) as exc:
        raise JwtError("invalid_token") from exc
    return AccessClaims(
        user_id=user_id,
        jti=jti,
        issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
    )


def mint_refresh_secret() -> tuple[str, str]:
    """Return ``(plaintext, sha256_hex)``. Plaintext is shown ONCE; storage holds the hash."""
    secret = secrets.token_urlsafe(32)
    hash_hex = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return secret, hash_hex


def hash_refresh_secret(plaintext: str) -> str:
    """Recompute the storage-side sha256 hex digest for a presented refresh secret."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


__all__ = [
    "ACCESS_TTL",
    "ALGORITHM",
    "ISSUER",
    "REFRESH_TTL",
    "AccessClaims",
    "JwtError",
    "SigningKey",
    "VerifyingKey",
    "decode_access_token",
    "hash_refresh_secret",
    "load_signing_keypair",
    "load_verifying_keys",
    "mint_access_token",
    "mint_refresh_secret",
]
