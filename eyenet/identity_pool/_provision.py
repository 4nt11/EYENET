# SPDX-License-Identifier: AGPL-3.0-or-later
"""The single provisioning path for operator identities.

Both the UI upload (``POST /v1/identities``) and the CLI import
(``eyenet identity sync``) call :func:`provision_identity`, so encryption
happens in exactly ONE place and the two paths cannot drift.

For Telegram the uploaded ``.session`` SQLite blob is converted to a portable
Telethon ``StringSession`` string (offline, no network round-trip), validated
(a real session carries an ``auth_key``), then Fernet-encrypted and written to
disk mode 0600. The plaintext session never persists server-side; the collector
decrypts the blob back into an in-memory ``StringSession`` at boot.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from telethon.sessions import SQLiteSession, StringSession

from eyenet.contracts.enums import IdentityRole, SourceKind
from eyenet.crypto import encrypt_session

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.contracts.identity import IdentityRow
    from eyenet.storage.repository import BaseRepository


class SessionValidationError(Exception):
    """The uploaded secret is not a usable session for its source.

    The API maps this to 422 — a bad blob is operator error, not a server fault.
    """


def _telegram_string_from_blob(blob: bytes) -> str:
    """Validate + convert a Telegram ``.session`` SQLite blob to a StringSession.

    Offline: Telethon reads the ``auth_key`` and DC straight out of the SQLite
    file. A blob that is not a SQLite database, or that carries no ``auth_key``,
    raises :class:`SessionValidationError`.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # Telethon appends ".session" to the session name; write the blob there.
        name = str(Path(tmp) / "upload")
        Path(name + ".session").write_bytes(blob)
        try:
            session = SQLiteSession(name)
        except sqlite3.DatabaseError as exc:
            raise SessionValidationError("not_a_valid_session_file") from exc
        try:
            if session.auth_key is None:
                raise SessionValidationError("session_missing_auth_key")
            # StringSession.save is untyped (telethon) → coerce the str result.
            return str(StringSession.save(session))
        finally:
            session.close()


def _materialize_secret(source_kind: SourceKind, secret_blob: bytes) -> str:
    """Source-dispatched: uploaded bytes -> the secret string we encrypt at rest.

    Telegram is the only source with a file-based secret today. New sources add
    a branch here (e.g. Matrix: decode the access token) — no other change.
    """
    if source_kind == SourceKind.TELEGRAM:
        return _telegram_string_from_blob(secret_blob)
    raise SessionValidationError(f"identity upload not supported for source: {source_kind.value}")


def _write_encrypted_blob(data_dir: Path, ciphertext: bytes) -> str:
    """Write the Fernet blob under ``<data_dir>/identities/`` mode 0600.

    tempfile-in-same-dir + atomic rename so a crash never leaves a half-written
    credential at the canonical path (mirrors ``storage/documents.py``).
    """
    blob_dir = data_dir / "identities"
    blob_dir.mkdir(parents=True, exist_ok=True)
    dest = blob_dir / f"{uuid4().hex}.enc"
    tmp = dest.with_suffix(".enc.partial")
    tmp.write_bytes(ciphertext)
    tmp.chmod(0o600)
    tmp.rename(dest)
    return str(dest)


async def provision_identity(
    *,
    storage: BaseRepository,
    session_key: Fernet,
    data_dir: Path,
    name: str,
    source_id: UUID,
    source_kind: SourceKind,
    secret_blob: bytes,
    source_config: dict[str, object],
    role: IdentityRole = IdentityRole.MONITOR,
    cooldown_seconds: int = 21_600,
    proxy_uri: str | None = None,
    notes: str | None = None,
) -> IdentityRow:
    """Validate, encrypt, and persist a new identity. Raises on duplicate name.

    ``secret_blob`` is the raw uploaded credential (Telegram: the ``.session``
    SQLite bytes). ``source_config`` holds the non-secret collector fields.
    """
    secret_string = _materialize_secret(source_kind, secret_blob)
    ciphertext = encrypt_session(session_key, secret_string)
    session_path = _write_encrypted_blob(data_dir, ciphertext)
    return await storage.create_identity(
        name=name,
        source_id=source_id,
        session_path=session_path,
        role=role,
        proxy_uri=proxy_uri,
        cooldown_seconds=cooldown_seconds,
        notes=notes,
        source_config=source_config,
    )


__all__ = ["SessionValidationError", "provision_identity"]
