# SPDX-License-Identifier: AGPL-3.0-or-later
"""`DbIdentityPool` — the DB-backed operator-identity pool.

The DB ``IdentityTable`` is the source of truth for credentials (M9.E5+): the
Fernet-encrypted session blob at ``session_path`` plus the non-secret
``source_config``. This pool is what live collectors claim against, replacing
the file-backed :class:`~eyenet.identity_pool.file.FileIdentityPool` (kept for
import + tests).

``claim`` reconstructs an :class:`~eyenet.identity_pool.loader.IdentityFileEntry`
from the row so collectors consume the identical object they always have — the
only new thing at collector boot is decrypting ``session_path`` (see
``eyenet.collectors.base._credentials``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from eyenet.contracts.enums import IdentityState, SourceKind
from eyenet.contracts.identity_pool import IdentityPool
from eyenet.contracts.source import SourceRow

from .loader import IdentityFileEntry

if TYPE_CHECKING:
    from eyenet.contracts.identity import IdentityRow
    from eyenet.storage.repository import BaseRepository


class DbIdentityPool(IdentityPool):
    """DB-backed identity pool. State transitions persist on the IdentityTable."""

    def __init__(self, storage: BaseRepository) -> None:
        self._storage = storage

    async def claim(self, name: str) -> IdentityFileEntry:
        row = await self._require(name)
        if row.state == IdentityState.IN_USE:
            raise RuntimeError(f"identity {name!r} is already in use")
        if row.state in (IdentityState.FROZEN, IdentityState.BURNED):
            raise RuntimeError(f"identity {name!r} is {row.state.value}")
        if row.state == IdentityState.COOLING and not self._cooldown_elapsed(row):
            raise RuntimeError(
                f"identity {name!r} still cooling; "
                f"cooldown_seconds={row.cooldown_seconds}, last_used_at={row.last_used_at}"
            )
        updated = await self._storage.set_identity_state(
            identity_id=row.id,
            state=IdentityState.IN_USE,
            last_used_at=datetime.now(tz=UTC),
        )
        return await self._to_entry(updated)

    async def release(self, name: str, *, new_state: IdentityState) -> None:
        row = await self._require(name)
        await self._storage.set_identity_state(
            identity_id=row.id,
            state=new_state,
            last_used_at=datetime.now(tz=UTC),
        )

    async def freeze_all(self) -> None:
        await self._storage.freeze_all_identities()

    # -- helpers ----------------------------------------------------------

    async def _require(self, name: str) -> IdentityRow:
        row = await self._storage.get_identity_by_name(name)
        if row is None:
            raise KeyError(f"unknown identity: {name!r}")
        return row

    @staticmethod
    def _cooldown_elapsed(row: IdentityRow) -> bool:
        if row.last_used_at is None:
            return True
        elapsed = (datetime.now(tz=UTC) - row.last_used_at).total_seconds()
        return elapsed >= row.cooldown_seconds

    async def _to_entry(self, row: IdentityRow) -> IdentityFileEntry:
        """Rebuild the collector-facing entry from the row + source_config.

        ``source_config`` holds exactly the per-source ``IdentityFileEntry``
        fields (telegram_api_id, monitor_groups, matrix_* ...), so the splat
        stays generic: a new source is a new key set, not new code here.
        """
        source = await self._storage.get_source(row.source_id)
        if not isinstance(source, SourceRow):
            raise RuntimeError(f"identity {row.name!r} references unknown source {row.source_id}")
        return IdentityFileEntry(
            name=row.name,
            source=SourceKind(source.kind),
            session_path=row.session_path,
            proxy_uri=row.proxy_uri,
            cooldown_seconds=row.cooldown_seconds,
            last_used_at=row.last_used_at,
            state=row.state,
            role=row.role,
            notes=row.notes,
            **row.source_config,
        )


__all__ = ["DbIdentityPool"]
