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
from pathlib import Path
from typing import TYPE_CHECKING

from eyenet.contracts.enums import IdentityRole, SourceKind
from eyenet.identity_pool._provision import provision_identity
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

    from eyenet.identity_pool.loader import IdentityFile, IdentityFileEntry
    from eyenet.storage.repository import BaseRepository

_log = get_logger()

# The non-secret per-source fields the DB row carries, keyed by IdentityFileEntry
# field name so DbIdentityPool can splat source_config back into an entry.
_SOURCE_CONFIG_FIELDS: dict[SourceKind, tuple[str, ...]] = {
    SourceKind.TELEGRAM: ("telegram_api_id", "telegram_api_hash", "monitor_groups"),
    SourceKind.MATRIX: (
        "matrix_homeserver_url",
        "matrix_user_id",
        "matrix_device_id",
        "matrix_monitor_rooms",
        "matrix_device_store_path",
    ),
}


def _source_config_from_entry(entry: IdentityFileEntry) -> dict[str, object]:
    fields = _SOURCE_CONFIG_FIELDS.get(entry.source, ())
    return {f: getattr(entry, f) for f in fields}


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
    session_key: Fernet | None = None,
    data_dir: Path | None = None,
) -> ProvisionResult:
    """Reconcile the file pool into the IdentityTable. Idempotent.

    When ``session_key`` + ``data_dir`` are supplied, a newly-created Telegram
    identity's plaintext ``.session`` (at the file entry's ``session_path``) is
    encrypted at rest through the shared :func:`provision_identity` path — the
    same encryption the UI upload uses, so CLI imports and UI uploads don't
    drift. Without them (tests / role-only reconciles) the row is created with
    the file's ``session_path`` unchanged.
    """
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
            source_config = _source_config_from_entry(entry)
            encrypt = (
                session_key is not None
                and data_dir is not None
                and entry.source == SourceKind.TELEGRAM
            )
            if encrypt:
                # One-shot read of the operator's plaintext .session at import
                # time (CLI `identity sync`), not a hot path — blocking IO here
                # is acceptable.
                blob = Path(entry.session_path).read_bytes()  # noqa: ASYNC240
                await provision_identity(
                    storage=storage,
                    session_key=session_key,  # type: ignore[arg-type]  # narrowed by `encrypt`
                    data_dir=data_dir,  # type: ignore[arg-type]
                    name=entry.name,
                    source_id=source_id,
                    source_kind=entry.source,
                    secret_blob=blob,
                    source_config=source_config,
                    role=role,
                    cooldown_seconds=entry.cooldown_seconds,
                    proxy_uri=entry.proxy_uri,
                    notes=entry.notes,
                )
            else:
                await storage.create_identity(
                    name=entry.name,
                    source_id=source_id,
                    session_path=entry.session_path,
                    role=role,
                    state=entry.state,
                    proxy_uri=entry.proxy_uri,
                    cooldown_seconds=entry.cooldown_seconds,
                    notes=entry.notes,
                    source_config=source_config,
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
