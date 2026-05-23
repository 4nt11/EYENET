"""`FileIdentityPool` — file-backed identity pool (PLAN §6).

State machine:
    AVAILABLE → IN_USE          (claim)
    IN_USE → COOLING            (release with cooldown_seconds remaining)
    IN_USE → AVAILABLE          (release, cooldown elapsed at release time)
    * → FROZEN                  (freeze_all / kill switch)
    * → BURNED                  (operator manual; pool refuses claim)

v0 simplification: the pool persists state on every `release`. Restart-safe.
Encryption-at-rest is M2 (the file path / type is forward-compatible).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from eyenet.contracts.enums import IdentityState
from eyenet.contracts.identity_pool import IdentityPool

from .loader import IdentityFile, IdentityFileEntry, dump, load


class FileIdentityPool(IdentityPool):
    """File-backed identity pool, single-process safe via an asyncio Lock."""

    def __init__(self, path: Path, *, check_session_files: bool = True) -> None:
        self._path = path
        self._file: IdentityFile = load(path, check_session_files=check_session_files)
        self._lock = asyncio.Lock()
        self._recover_stale_in_use()

    async def claim(self, name: str) -> IdentityFileEntry:
        async with self._lock:
            entry = self._find(name)
            if entry.state == IdentityState.IN_USE:
                raise RuntimeError(f"identity {name!r} is already in use")
            if entry.state in (IdentityState.FROZEN, IdentityState.BURNED):
                raise RuntimeError(f"identity {name!r} is {entry.state.value}")
            if entry.state == IdentityState.COOLING and not self._cooldown_elapsed(entry):
                raise RuntimeError(
                    f"identity {name!r} still cooling; "
                    f"cooldown_seconds={entry.cooldown_seconds}, "
                    f"last_used_at={entry.last_used_at}"
                )
            entry.state = IdentityState.IN_USE
            entry.last_used_at = datetime.now(tz=UTC)
            self._persist()
            return entry

    async def release(self, name: str, *, new_state: IdentityState) -> None:
        async with self._lock:
            entry = self._find(name)
            entry.state = new_state
            entry.last_used_at = datetime.now(tz=UTC)
            self._persist()

    async def freeze_all(self) -> None:
        async with self._lock:
            for entry in self._file.identities:
                if entry.state != IdentityState.BURNED:
                    entry.state = IdentityState.FROZEN
            self._persist()

    # -- helpers ----------------------------------------------------------

    def _find(self, name: str) -> IdentityFileEntry:
        for entry in self._file.identities:
            if entry.name == name:
                return entry
        raise KeyError(f"unknown identity: {name!r}")

    def _cooldown_elapsed(self, entry: IdentityFileEntry) -> bool:
        if entry.last_used_at is None:
            return True
        elapsed = (datetime.now(tz=UTC) - entry.last_used_at).total_seconds()
        return elapsed >= entry.cooldown_seconds

    def _recover_stale_in_use(self) -> None:
        """Reset IN_USE → AVAILABLE on startup.

        If the previous process crashed or was killed before release(), identities
        are left IN_USE in the TOML. Since no process can still be holding them
        (we're constructing a fresh pool), recover them so the operator doesn't
        have to edit the file manually.
        """
        recovered = False
        for entry in self._file.identities:
            if entry.state == IdentityState.IN_USE:
                entry.state = IdentityState.AVAILABLE
                recovered = True
        if recovered:
            self._persist()

    def _persist(self) -> None:
        dump(self._file, self._path)


__all__ = ["FileIdentityPool"]
