# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector credential materialization — the decrypt-on-boot seam.

A live collector never opens ``session_path`` off disk directly any more: the
blob there is Fernet-encrypted (see ``eyenet.identity_pool._provision``). Each
source gets a small materializer here that turns the claimed
:class:`~eyenet.identity_pool.loader.IdentityFileEntry` into the in-memory
credential its client wants. New source = new function here, one place.

Plaintext stays off disk end-to-end: the Telegram session is decrypted into an
in-memory Telethon ``StringSession``, never written back out.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from telethon.sessions import StringSession

from eyenet.crypto import decrypt_session

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.identity_pool.loader import IdentityFileEntry


def materialize_telegram_session(
    entry: IdentityFileEntry,
    session_key: Fernet | None,
) -> str | StringSession:
    """Return the session object to hand to ``TelegramClient``.

    - ``session_key`` set (DB-backed pool): decrypt the Fernet blob at
      ``session_path`` into an in-memory :class:`StringSession`.
    - ``session_key`` is ``None`` (legacy file pool): pass the plaintext
      ``session_path`` through unchanged so Telethon opens it as a file.
    """
    if session_key is None:
        return entry.session_path
    ciphertext = Path(entry.session_path).read_bytes()
    return StringSession(decrypt_session(session_key, ciphertext))


__all__ = ["materialize_telegram_session"]
