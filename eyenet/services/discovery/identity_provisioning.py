# SPDX-License-Identifier: AGPL-3.0-or-later
"""File↔DB identity bridge (API_PLAN §4.12, M9.E5).

The file pool (`identities.toml`) is the credential/session store; the
`IdentityTable` is the discovery-loop source of truth for role/state. Until an
identity exists in the DB, the supervisor's `lease_scout` returns nothing and
the discovery loop can't recurse.

:func:`provision_identities` reconciles the file into the DB: it upserts the
Source (same `display_name` convention the collector uses, so the rows line up),
creates a missing `IdentityTable` row per file entry (role from the entry's
optional ``role`` field, default MONITOR), and updates the role of an existing
row when the file disagrees. Runtime state (lease / burn) is owned by the DB and
is never clobbered from the file — only the role is reconciled.

Pure and idempotent: safe to run on every boot or via ``eyenet identity sync``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from eyenet.contracts.enums import IdentityRole
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from eyenet.identity_pool.loader import IdentityFile
    from eyenet.storage.repository import BaseRepository

_log = get_logger()


@dataclass(frozen=True)
class ProvisionResult:
    """Names of identities created / role-updated / left unchanged."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


async def provision_identities(
    storage: BaseRepository,
    pool_file: IdentityFile,
    *,
    now: datetime | None = None,
) -> ProvisionResult:
    """Reconcile the file pool into the IdentityTable. Idempotent."""
    at = now or datetime.now(tz=UTC)
    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    for entry in pool_file.identities:
        source_id = await storage.upsert_source(
            kind=entry.source,
            display_name=f"{entry.source.value}:{entry.name}",
            created_at=at,
        )
        role = entry.role or IdentityRole.MONITOR
        existing = await storage.list_identities(source_id=source_id)
        match = next((i for i in existing if i.name == entry.name), None)

        if match is None:
            await storage.create_identity(
                name=entry.name,
                source_id=source_id,
                session_path=entry.session_path,
                role=role,
                state=entry.state,
                proxy_uri=entry.proxy_uri,
                cooldown_seconds=entry.cooldown_seconds,
                notes=entry.notes,
            )
            created.append(entry.name)
        elif match.role is not role:
            await storage.set_identity_role(identity_id=match.id, role=role)
            updated.append(entry.name)
        else:
            unchanged.append(entry.name)

    _log.info(
        "identity.provisioned",
        created=len(created),
        updated=len(updated),
        unchanged=len(unchanged),
    )
    return ProvisionResult(created=created, updated=updated, unchanged=unchanged)


__all__ = ["ProvisionResult", "provision_identities"]
