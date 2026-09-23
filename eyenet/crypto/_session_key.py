# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fernet at-rest encryption for collector session credentials.

Single symmetric key at ``<data_dir>/jwt/session_fernet.key``, mode 0600.
Generated on first call alongside the other boot keys (same operator backup
story as ``mfa_key`` / the JWT keypair). This key protects the most sensitive
material EYENET stores: a Telegram ``.session`` (serialized to a Telethon
``StringSession`` before encryption) is a full account-takeover credential.

Losing this file = every provisioned identity must be re-uploaded (the operator
re-mints each ``.session`` out-of-band). It is deliberately the SAME shape as
:mod:`eyenet.api.auth._mfa_key` so there is one at-rest-key convention to reason
about, not two.

Rotation is a manual two-step (decrypt-all-with-old / re-encrypt-with-new), same
as MFA-key rotation. Not exposed as a CLI here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from pathlib import Path

_SESSION_KEY_NAME: Final[str] = "session_fernet.key"


class SessionKeyError(Exception):
    """Internal — wraps Fernet decrypt failures (tampered blob / wrong key)."""


def _ensure_jwt_dir(data_dir: Path) -> Path:
    jwt_dir = data_dir / "jwt"
    jwt_dir.mkdir(parents=True, exist_ok=True)
    return jwt_dir


def load_session_key(data_dir: Path) -> Fernet:
    """Return a configured :class:`Fernet`, materializing the key on first call."""
    jwt_dir = _ensure_jwt_dir(data_dir)
    key_path = jwt_dir / _SESSION_KEY_NAME
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        key_path.chmod(0o600)
    return Fernet(key_path.read_bytes())


def encrypt_session(fernet: Fernet, plaintext: str) -> bytes:
    """Encrypt a session secret (e.g. a StringSession). Output is the raw blob."""
    return fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_session(fernet: Fernet, ciphertext: bytes) -> str:
    """Decrypt a previously-encrypted session secret.

    Raises :class:`SessionKeyError` on a tampered blob or wrong key — the
    collector fails closed (the identity cannot be opened) rather than leaking
    which of the two it was.
    """
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise SessionKeyError("invalid_or_tampered_session_blob") from exc


__all__ = [
    "SessionKeyError",
    "decrypt_session",
    "encrypt_session",
    "load_session_key",
]
