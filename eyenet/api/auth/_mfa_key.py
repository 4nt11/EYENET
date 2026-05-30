# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fernet at-rest encryption for TOTP secrets (M9.A3).

Single symmetric key at ``<data_dir>/jwt/mfa_key``, mode 0600. Generated
on first call alongside the JWT signing keypair (same boot path,
same operator backup story). Losing this file = every enrolled user must
re-enroll (operator runs ``eyenet user reset-mfa --all`` from A6).

Rotation is a manual two-step (decrypt-all-with-old / re-encrypt-with-new)
documented in ``development/MFA_OPS.md``. Not exposed as a CLI in A3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from cryptography.fernet import Fernet, InvalidToken

_MFA_KEY_NAME: Final[str] = "mfa_key"


class MfaKeyError(Exception):
    """Internal — wraps Fernet decrypt failures."""


def _ensure_jwt_dir(data_dir: Path) -> Path:
    jwt_dir = data_dir / "jwt"
    jwt_dir.mkdir(parents=True, exist_ok=True)
    return jwt_dir


def load_mfa_key(data_dir: Path) -> Fernet:
    """Return a configured :class:`Fernet`, materializing the key on first call."""
    jwt_dir = _ensure_jwt_dir(data_dir)
    key_path = jwt_dir / _MFA_KEY_NAME
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        key_path.chmod(0o600)
    return Fernet(key_path.read_bytes())


def encrypt_secret(fernet: Fernet, plaintext: str) -> str:
    """Encrypt a TOTP secret. Output is opaque base64 — store as-is."""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(fernet: Fernet, ciphertext: str) -> str:
    """Decrypt a previously-encrypted TOTP secret.

    Raises :class:`MfaKeyError` on tampered ciphertext or wrong key —
    callers translate to a 401 ProblemDetail (no oracle in the wire body).
    """
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise MfaKeyError("invalid_or_tampered_ciphertext") from exc


__all__ = [
    "MfaKeyError",
    "decrypt_secret",
    "encrypt_secret",
    "load_mfa_key",
]
