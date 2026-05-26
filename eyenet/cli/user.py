"""``eyenet user *`` — operator surface for system-user state (M9.A3+).

A3 ships exactly one command: ``unlock-mfa``. A6 extends this file with
``create``, ``reset-password``, ``scopes``, and ``reset-mfa``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from eyenet.bus.memory import MemoryBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.cli.config import RuntimeConfig
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

user_app = typer.Typer(
    name="user",
    help="Operator surface for system-user state.",
    no_args_is_help=True,
)

_UNLOCK_WINDOW = timedelta(minutes=15)


@user_app.command("unlock-mfa")
def unlock_mfa(
    username: str = typer.Argument(..., help="System-user username to unlock."),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Zero ``failed_attempts`` on all of the user's recent MFA challenge rows.

    Clears the 5-fail / 15-min lockout window without resetting the user's
    enrolled TOTP secret. Use ``eyenet user reset-mfa`` (A6) for lost-device
    recovery — that command also wipes the secret.
    """
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_unlock_mfa(storage, username))


async def _unlock_mfa(storage: BaseRepository, username: str) -> None:
    user = await storage.get_system_user_by_username(username)
    if user is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=2)

    now = datetime.now(tz=UTC)
    cleared = await storage.clear_mfa_failures(
        user_id=user.id,
        since=now - _UNLOCK_WINDOW,
    )

    audit = AuditEmitter(
        BusEnvelopePublisher(MemoryBus()),
        storage,
        service="cli",
        instance_id=f"cli-{os.getpid()}",
    )
    await audit.emit(
        event="eyenet.audit.auth.mfa.unlocked",
        subject_kind="system_user",
        subject_id=user.id,
        system_user_id=user.id,
        payload={"username": username, "rows_cleared": cleared},
    )
    typer.echo(f"unlocked {username}: cleared {cleared} failed-challenge row(s).")


__all__ = ["user_app"]
