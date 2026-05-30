# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for the linkage read handlers (M9.F2)."""

from __future__ import annotations

from uuid import UUID

from eyenet.storage.repository import BaseRepository


async def resolve_decider(
    storage: BaseRepository,
    username: str | None,
    cache: dict[str, UUID | None],
) -> UUID | None:
    """Resolve a linkage's ``decided_by`` username to a SystemUser id.

    The domain row stores the decider as a username string; the API contract
    exposes the UUID. Returns ``None`` when the linkage is undecided or the
    username no longer maps to a known SystemUser (both valid per the schema).
    ``cache`` dedups lookups within a single request.
    """
    if username is None:
        return None
    if username not in cache:
        user = await storage.get_system_user_by_username(username)
        cache[username] = user.id if user is not None else None
    return cache[username]
