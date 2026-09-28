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

import httpx
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


# Netscape cookies.txt columns: domain, flag, path, secure, expiry, name, value.
_NETSCAPE_COOKIE_FIELDS = 7


def _parse_netscape_cookies(text: str) -> httpx.Cookies:
    """Parse a browser-exported Netscape ``cookies.txt`` into ``httpx.Cookies``.

    The operator logs into the forum in a real browser (solving the captcha by
    hand, once) and exports the session cookies with any "cookies.txt" extension.
    That standard 7-column tab-separated format is stdlib-parseable; no external
    cookie library. The ``#HttpOnly_`` domain prefix some exporters emit is
    stripped and treated as a normal cookie.
    """
    jar = httpx.Cookies()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != _NETSCAPE_COOKIE_FIELDS:
            continue
        domain, _flag, path, _secure, _expiry, name, value = fields
        jar.set(name, value, domain=domain, path=path)
    return jar


def materialize_forum_session(
    entry: IdentityFileEntry,
    session_key: Fernet | None,
) -> httpx.Cookies:
    """Return the cookie jar to hand to the forum ``httpx.AsyncClient``.

    The exported browser cookies.txt is stored at ``session_path`` — the same
    generic secret slot the telegram StringSession uses — so both pools share one
    decrypt-on-boot seam:

    - ``session_key`` set (DB-backed pool): decrypt the Fernet blob at
      ``session_path`` in memory; the plaintext cookies never touch disk.
    - ``session_key`` is ``None`` (legacy file pool): read the plaintext
      cookies.txt at ``session_path`` directly.
    """
    path = Path(entry.session_path)
    if session_key is None:
        return _parse_netscape_cookies(path.read_text(encoding="utf-8"))
    return _parse_netscape_cookies(decrypt_session(session_key, path.read_bytes()))


__all__ = ["materialize_forum_session", "materialize_telegram_session"]
