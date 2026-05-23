"""Interactive MTProto session bootstrap for a Telegram identity.

Called once, before the collector service starts, when the session file is
absent. Prompts for phone number and OTP on stdin, writes the .session file,
then exits. Subsequent runs skip this entirely.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eyenet.identity_pool.loader import IdentityFileEntry


def session_exists(entry: IdentityFileEntry) -> bool:
    """Return True if the Telethon session file already exists."""
    p = Path(entry.session_path)
    # Telethon appends .session when the path has no extension.
    return p.exists() or p.with_suffix(".session").exists()


async def _authenticate(entry: IdentityFileEntry) -> None:
    from telethon import TelegramClient  # noqa: PLC0415

    if entry.telegram_api_id is None or entry.telegram_api_hash is None:
        raise ValueError(
            f"identity {entry.name!r} is missing telegram_api_id / "
            "telegram_api_hash in identities.toml"
        )

    session_dir = Path(entry.session_path).parent
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[eyenet] Authenticating identity '{entry.name}' via MTProto.")
    print(f"[eyenet] Session will be saved to: {entry.session_path}.session\n")

    client = TelegramClient(
        entry.session_path,
        entry.telegram_api_id,
        entry.telegram_api_hash,
    )

    await client.start()  # prompts for phone + OTP interactively
    me = await client.get_me()
    print(f"\n[eyenet] Authenticated as: {getattr(me, 'username', None) or getattr(me, 'id', '?')}")
    await client.disconnect()


def ensure_session(entry: IdentityFileEntry) -> None:
    """Block until the session file exists, running auth interactively if needed."""
    if session_exists(entry):
        return
    asyncio.run(_authenticate(entry))


__all__ = ["ensure_session", "session_exists"]
