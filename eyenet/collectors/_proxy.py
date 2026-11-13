# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lease + convert a pooled proxy into a client-specific config (v1.2.0).

Each client type wants a different shape:

- **Telethon** (TG): a tuple ``(socks.SOCKS5 | socks.HTTP, host, port)`` for
  anonymous proxies, or ``(stype, host, port, rdns, user, pass)`` with auth.
- **httpx** (forum): a proxy URL string ``socks5://[user:pass@]host:port``.
- **nio** (matrix): not wired yet, follow-up.

Both helpers pull from the storage lease (sticky/non-sticky driven by
``identity.proxy_sticky`` + source-kind default), decrypt the Fernet-sealed
credential half, and return ``None`` when the identity has no pool
attached, so callers fall back to the legacy ``entry.proxy_uri`` path or
to a direct connection.

MTPROXY is not covered here: Telethon's ``ConnectionTcpMTProxy*`` path
needs a different TelegramClient constructor keyword (``connection=`` plus
``proxy=(host, port, secret_bytes)``), not a generic tuple. Left as a
follow-up when we first ship an MTProto entry to prod.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from eyenet.contracts.enums import ProxyKind, SourceKind

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.contracts.proxy import ProxyRow
    from eyenet.storage.repository import BaseRepository


def _decrypt_user_pass(blob: bytes | None, fernet: Fernet) -> tuple[str | None, str | None]:
    """Decrypt a ``b"user:pass"`` or ``b"user"`` credential blob.

    Returns ``(None, None)`` when no credential is stored, ``(user, None)``
    when only a username is stored (rare; some providers use a token-only
    SOCKS5), and ``(user, pass)`` for the normal case.
    """
    if blob is None:
        return (None, None)
    try:
        raw = fernet.decrypt(blob).decode("utf-8")
    except Exception:  # noqa: BLE001 - caller logs; a bad credential should not crash start
        return (None, None)
    if ":" in raw:
        user, pw = raw.split(":", 1)
        return (user, pw)
    return (raw or None, None)


async def lease_telethon_proxy(
    storage: BaseRepository,
    identity_id: UUID,
    *,
    source_kind: SourceKind,
    fernet: Fernet,
) -> tuple | None:
    """Lease a proxy and shape it for :class:`telethon.TelegramClient`.

    Returns ``None`` when the identity is not pool-attached or the pool has
    no eligible proxy. Returns a 3-tuple (anonymous) or 6-tuple (auth)
    PySocks tuple otherwise. MTPROXY entries in the pool are skipped here
    (the TG client needs a different constructor shape for those).
    """
    row: ProxyRow | None = await storage.lease_proxy_for_identity(
        identity_id, source_kind=source_kind
    )
    if row is None or row.kind == ProxyKind.MTPROXY:
        return None
    import socks  # noqa: PLC0415 - lazy PySocks load

    stype_map = {
        ProxyKind.SOCKS5: socks.SOCKS5,
        ProxyKind.HTTP: socks.HTTP,
        ProxyKind.HTTPS: socks.HTTP,
    }
    stype = stype_map.get(row.kind)
    if stype is None:
        return None
    user, password = _decrypt_user_pass(row.secret_encrypted, fernet)
    if user:
        # rdns=True: let the proxy resolve DNS so Telegram DC hostnames
        # don't leak to local DNS. Matches python-telethon default advice.
        return (stype, row.host, row.port, True, user, password or "")
    return (stype, row.host, row.port)


async def lease_httpx_proxy_url(
    storage: BaseRepository,
    identity_id: UUID,
    *,
    source_kind: SourceKind,
    fernet: Fernet,
) -> str | None:
    """Lease a proxy and shape it as an httpx-compatible URL.

    Returns ``None`` when the identity is not pool-attached or the pool has
    no eligible proxy. HTTPS proxies collapse to the ``http`` scheme per
    httpx's convention (the ``s`` was always about where the destination
    was, not the hop to the proxy).
    """
    row: ProxyRow | None = await storage.lease_proxy_for_identity(
        identity_id, source_kind=source_kind
    )
    if row is None or row.kind == ProxyKind.MTPROXY:
        return None
    scheme_map = {
        ProxyKind.SOCKS5: "socks5",
        ProxyKind.HTTP: "http",
        ProxyKind.HTTPS: "http",
    }
    scheme = scheme_map.get(row.kind)
    if scheme is None:
        return None
    user, password = _decrypt_user_pass(row.secret_encrypted, fernet)
    auth = ""
    if user:
        # urllib-style escape: callers rarely need special chars, but a
        # ``@`` in a password would corrupt parsing on the other side.
        from urllib.parse import quote  # noqa: PLC0415 - rare path

        auth = f"{quote(user, safe='')}:{quote(password or '', safe='')}@"
    return f"{scheme}://{auth}{row.host}:{row.port}"


__all__ = ["lease_httpx_proxy_url", "lease_telethon_proxy"]
