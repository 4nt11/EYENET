"""``eyenet user *`` — operator surface for system-user state (M9.A3+).

Commands:

- ``unlock-mfa`` (A3) — clear an MFA lockout without touching enrollment.
- ``create`` / ``reset-password`` / ``scopes`` / ``reset-mfa`` (A6).

**Authorizer gate.** Every *mutating* A6 command requires ``--as <username>``
naming the operator performing the action. The CLI hidden-prompts for that
operator's password (argon2id verify) and — if they are MFA-enrolled — a live
TOTP code, then checks they hold ``admin:users``. This turns "shell access on
the box = total control" into "shell access **plus a privileged credential** =
control": the argon2id password hash is not recoverable from the disk, unlike
the Fernet-encrypted TOTP seed. (``scopes list`` is read-only and ungated.)

The one exception is the *bootstrap* ``create``: when no system user exists
yet there is no operator to authenticate against, so the first ``create`` is
allowed un-gated and forced to ``role=admin`` so the operator cannot strand
themselves with a permissionless account.

Exit codes: ``0`` ok · ``2`` unknown user/scope or usage error · ``3``
authorizer authentication failure (bad password/TOTP) · ``4`` authorizer
lacks ``admin:users`` · ``5`` clearance scope refused.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

import typer
from nats import errors as nats_errors

from eyenet.api.auth import (
    ROLE_BASELINE,
    MfaKeyError,
    decrypt_secret,
    hash_password,
    load_mfa_key,
    resolve_effective_scopes,
    verify_code,
    verify_password,
)
from eyenet.bus.memory import MemoryBus
from eyenet.bus.nats import NATSBus
from eyenet.bus.publisher import BusEnvelopePublisher
from eyenet.cli.config import RuntimeConfig
from eyenet.contracts.enums import ClearanceScope, SystemUserRole
from eyenet.contracts.system_user import SystemUserRow
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

user_app = typer.Typer(
    name="user",
    help="Operator surface for system-user state.",
    no_args_is_help=True,
)
scopes_app = typer.Typer(
    name="scopes",
    help="Manage explicit per-user scope grants (additive to the role baseline).",
    no_args_is_help=True,
)
user_app.add_typer(scopes_app, name="scopes")

_UNLOCK_WINDOW = timedelta(minutes=15)

_ADMIN_USERS_SCOPE: Final[str] = "admin:users"
_SCOPES_CHANGED_SUBJECT: Final[str] = "eyenet.auth.scopes_changed"

# Explicitly grantable via the CLI: every scope that appears in some role
# baseline. The grant-only clearance scopes are deliberately NOT here — they
# flow through the time-bound clearance-grant path (bounded expiry + reason).
_GRANTABLE: Final[frozenset[str]] = frozenset().union(*ROLE_BASELINE.values())
_CLEARANCE: Final[frozenset[str]] = frozenset(s.value for s in ClearanceScope)

_EXIT_USAGE: Final[int] = 2
_EXIT_AUTH: Final[int] = 3
_EXIT_PERM: Final[int] = 4
_EXIT_CLEARANCE_REFUSED: Final[int] = 5

_PW_ALPHABET: Final[str] = string.ascii_letters + string.digits + "!@#$%^&*-_=+"


def _gen_password(length: int = 24) -> str:
    """A strong random password from a `secrets`-backed alphabet."""
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


def _audit_emitter(storage: BaseRepository) -> AuditEmitter:
    """A CLI-tagged audit emitter (writes the chained row to storage)."""
    return AuditEmitter(
        BusEnvelopePublisher(MemoryBus()),
        storage,
        service="cli",
        instance_id=f"cli-{os.getpid()}",
    )


async def _authorize(
    storage: BaseRepository,
    data_dir: Path,
    *,
    actor_username: str,
    require_scope: str,
    now: datetime,
) -> SystemUserRow:
    """Authenticate ``--as`` and confirm it holds ``require_scope``.

    Password (argon2id) + conditional TOTP step-up (only when the authorizer
    is MFA-enrolled) + effective-scope check. Any failure is fatal: exit 3
    (bad credential) or exit 4 (insufficient scope). Returns the authorizer
    row so callers can record it as ``granted_by`` / ``system_user_id``.
    """
    actor = await storage.get_system_user_by_username(actor_username)
    if actor is None:
        typer.echo("error: authorization failed", err=True)
        raise typer.Exit(code=_EXIT_AUTH)
    cred = await storage.get_credential(actor.id)
    if cred is None:
        typer.echo("error: authorization failed", err=True)
        raise typer.Exit(code=_EXIT_AUTH)

    password: str = typer.prompt(f"Password for {actor_username}", hide_input=True)
    if not verify_password(password, cred.password_hash):
        typer.echo("error: authorization failed", err=True)
        raise typer.Exit(code=_EXIT_AUTH)

    if cred.mfa_secret_encrypted is not None:
        code: str = typer.prompt(f"TOTP code for {actor_username}", hide_input=True)
        try:
            seed = decrypt_secret(load_mfa_key(data_dir), cred.mfa_secret_encrypted)
        except MfaKeyError:
            typer.echo("error: authorization failed", err=True)
            raise typer.Exit(code=_EXIT_AUTH) from None
        if not verify_code(secret_b32=seed, code=code, now=now):
            typer.echo("error: authorization failed", err=True)
            raise typer.Exit(code=_EXIT_AUTH)
    else:
        typer.echo(
            f"warning: authorizer {actor_username!r} has no MFA enrolled — "
            "password-only authorization",
            err=True,
        )

    effective = resolve_effective_scopes(
        actor,
        await storage.list_explicit_scopes(actor.id),
        await storage.active_clearance_grants_for(actor.id, now=now),
    )
    if require_scope not in effective:
        typer.echo(f"error: {actor_username!r} lacks {require_scope!r}", err=True)
        raise typer.Exit(code=_EXIT_PERM)
    return actor


async def _publish_scopes_changed(cfg: RuntimeConfig, user_id: UUID) -> None:
    """Best-effort cross-process scope-cache eviction (API_PLAN §4.4.1).

    The grant/revoke has already committed to storage; this only *accelerates*
    eviction in running API processes. A missing broker is non-fatal — caches
    refresh on their TTL regardless — so an unreachable NATS warns and returns.
    """
    payload = json.dumps({"user_id": str(user_id)}).encode("utf-8")
    try:
        bus = await NATSBus.connect(cfg.nats_url)
    except (OSError, nats_errors.Error) as exc:
        typer.echo(
            f"warning: scopes saved; NATS unreachable ({type(exc).__name__}) — "
            "API caches refresh on TTL",
            err=True,
        )
        return
    try:
        await bus.publish(_SCOPES_CHANGED_SUBJECT, payload)
    finally:
        await bus.close()


@user_app.command("unlock-mfa")
def unlock_mfa(
    username: str = typer.Argument(..., help="System-user username to unlock."),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Zero ``failed_attempts`` on all of the user's recent MFA challenge rows.

    Clears the 5-fail / 15-min lockout window without resetting the user's
    enrolled TOTP secret. Use ``eyenet user reset-mfa`` for lost-device
    recovery — that command also wipes the secret.
    """
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_unlock_mfa(storage, username))


async def _unlock_mfa(storage: BaseRepository, username: str) -> None:
    user = await storage.get_system_user_by_username(username)
    if user is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    now = datetime.now(tz=UTC)
    cleared = await storage.clear_mfa_failures(
        user_id=user.id,
        since=now - _UNLOCK_WINDOW,
    )

    audit = _audit_emitter(storage)
    await audit.emit(
        event="eyenet.audit.auth.mfa.unlocked",
        subject_kind="system_user",
        subject_id=user.id,
        system_user_id=user.id,
        payload={"username": username, "rows_cleared": cleared},
    )
    typer.echo(f"unlocked {username}: cleared {cleared} failed-challenge row(s).")


@user_app.command("create")
def create(
    username: str = typer.Argument(..., help="Username for the new system user."),
    role: SystemUserRole = typer.Option(
        SystemUserRole.VIEWER,
        "--role",
        help="Role for the new user (forced to admin on the bootstrap first user).",
    ),
    display_name: str | None = typer.Option(
        None, "--display-name", help="Defaults to the username."
    ),
    email: str | None = typer.Option(None, "--email"),
    as_user: str | None = typer.Option(
        None,
        "--as",
        help="Authorizer username (must hold admin:users). Required unless "
        "bootstrapping the very first user.",
    ),
    generate: bool = typer.Option(
        False, "--generate", help="Generate a strong random password and print it once."
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Create a system user and its credential row.

    Gated behind ``--as`` + password + TOTP step-up, except for the bootstrap
    first user (empty table → no authorizer, forced ``--role admin``).
    """
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    password = _gen_password() if generate else None
    asyncio.run(
        _create(
            storage,
            cfg.data_dir,
            username=username,
            role=role,
            display_name=display_name,
            email=email,
            as_user=as_user,
            password=password,
            generate=generate,
        )
    )


async def _create(
    storage: BaseRepository,
    data_dir: Path,
    *,
    username: str,
    role: SystemUserRole,
    display_name: str | None,
    email: str | None,
    as_user: str | None,
    password: str | None,
    generate: bool,
) -> None:
    now = datetime.now(tz=UTC)
    if await storage.get_system_user_by_username(username) is not None:
        typer.echo(f"error: user {username!r} already exists", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    bootstrap = await storage.count_system_users() == 0
    authorizer: SystemUserRow | None
    if bootstrap:
        if role is not SystemUserRole.ADMIN:
            typer.echo(
                "error: the first user must be created with --role admin "
                "(otherwise no one can authorize future commands)",
                err=True,
            )
            raise typer.Exit(code=_EXIT_USAGE)
        authorizer = None
    else:
        if as_user is None:
            typer.echo(
                "error: --as <authorizer> is required (a system user already exists)",
                err=True,
            )
            raise typer.Exit(code=_EXIT_USAGE)
        authorizer = await _authorize(
            storage,
            data_dir,
            actor_username=as_user,
            require_scope=_ADMIN_USERS_SCOPE,
            now=now,
        )

    if password is None:
        password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)

    new_id = new_uuid7()
    await storage.put_system_user(
        user_id=new_id,
        username=username,
        display_name=display_name or username,
        role=role,
        created_at=now,
        email=email,
    )
    await storage.put_credential(
        user_id=new_id,
        password_hash=hash_password(password),
        password_updated_at=now,
    )

    audit = _audit_emitter(storage)
    await audit.emit(
        event="eyenet.audit.auth.user.created",
        subject_kind="system_user",
        subject_id=new_id,
        system_user_id=new_id if authorizer is None else authorizer.id,
        payload={"username": username, "role": role.value, "bootstrap": bootstrap},
    )
    if generate:
        typer.echo(f"generated password (store now, shown once): {password}")
    typer.echo(f"created user {username!r} ({role.value})")


@user_app.command("reset-password")
def reset_password(
    username: str = typer.Argument(..., help="System-user username."),
    as_user: str = typer.Option(..., "--as", help="Authorizer username (must hold admin:users)."),
    generate: bool = typer.Option(
        False, "--generate", help="Generate a strong random password and print it once."
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Set a new password for a user, preserving any MFA enrollment."""
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    password = _gen_password() if generate else None
    asyncio.run(
        _reset_password(
            storage,
            cfg.data_dir,
            username=username,
            as_user=as_user,
            password=password,
            generate=generate,
        )
    )


async def _reset_password(
    storage: BaseRepository,
    data_dir: Path,
    *,
    username: str,
    as_user: str,
    password: str | None,
    generate: bool,
) -> None:
    now = datetime.now(tz=UTC)
    authorizer = await _authorize(
        storage, data_dir, actor_username=as_user, require_scope=_ADMIN_USERS_SCOPE, now=now
    )
    target = await storage.get_system_user_by_username(username)
    if target is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)
    cred = await storage.get_credential(target.id)
    if cred is None:
        typer.echo(f"error: user {username!r} has no credential row", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    if password is None:
        password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)

    await storage.put_credential(
        user_id=target.id,
        password_hash=hash_password(password),
        password_updated_at=now,
        mfa_secret_encrypted=cred.mfa_secret_encrypted,  # preserve MFA enrollment
    )
    audit = _audit_emitter(storage)
    await audit.emit(
        event="eyenet.audit.auth.password.reset",
        subject_kind="system_user",
        subject_id=target.id,
        system_user_id=authorizer.id,
        payload={"username": username},
    )
    if generate:
        typer.echo(f"generated password (store now, shown once): {password}")
    typer.echo(f"reset password for {username!r}")


@user_app.command("reset-mfa")
def reset_mfa(
    username: str = typer.Argument(..., help="System-user username."),
    as_user: str = typer.Option(..., "--as", help="Authorizer username (must hold admin:users)."),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Wipe a user's MFA enrollment (lost-device recovery).

    Unlike ``unlock-mfa`` (which only clears a lockout), this deletes the
    encrypted TOTP secret and clears the lockout window, forcing the user to
    re-enroll at ``/v1/auth/mfa/enroll``.
    """
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_reset_mfa(storage, cfg.data_dir, username=username, as_user=as_user))


async def _reset_mfa(
    storage: BaseRepository,
    data_dir: Path,
    *,
    username: str,
    as_user: str,
) -> None:
    now = datetime.now(tz=UTC)
    authorizer = await _authorize(
        storage, data_dir, actor_username=as_user, require_scope=_ADMIN_USERS_SCOPE, now=now
    )
    target = await storage.get_system_user_by_username(username)
    if target is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)
    cred = await storage.get_credential(target.id)
    if cred is None:
        typer.echo(f"error: user {username!r} has no credential row", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    await storage.put_credential(
        user_id=target.id,
        password_hash=cred.password_hash,
        password_updated_at=cred.password_updated_at,
        mfa_secret_encrypted=None,  # wipe enrollment
    )
    cleared = await storage.clear_mfa_failures(user_id=target.id, since=now - _UNLOCK_WINDOW)
    audit = _audit_emitter(storage)
    await audit.emit(
        event="eyenet.audit.auth.mfa.reset",
        subject_kind="system_user",
        subject_id=target.id,
        system_user_id=authorizer.id,
        payload={"username": username, "failures_cleared": cleared},
    )
    typer.echo(
        f"reset MFA for {username!r}: enrollment wiped; user must re-enroll at /v1/auth/mfa/enroll."
    )


@scopes_app.command("grant")
def scopes_grant(
    username: str = typer.Argument(..., help="System-user username."),
    scopes: list[str] = typer.Argument(..., help="One or more scopes to grant."),
    as_user: str = typer.Option(
        ...,
        "--as",
        help="Authorizer username (must hold admin:users); recorded as granted_by.",
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Grant explicit scopes to a user (additive to the role baseline).

    Refuses the grant-only clearance scopes — those flow through the
    time-bound clearance-grant path, not a permanent CLI grant.
    """
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_scopes_grant(storage, cfg, username=username, scopes=scopes, as_user=as_user))


async def _scopes_grant(
    storage: BaseRepository,
    cfg: RuntimeConfig,
    *,
    username: str,
    scopes: list[str],
    as_user: str,
) -> None:
    now = datetime.now(tz=UTC)
    authorizer = await _authorize(
        storage, cfg.data_dir, actor_username=as_user, require_scope=_ADMIN_USERS_SCOPE, now=now
    )
    target = await storage.get_system_user_by_username(username)
    if target is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    # Validate ALL scopes before writing any — no partial grant on a bad arg.
    for scope in scopes:
        if scope in _CLEARANCE:
            typer.echo(
                f"error: {scope!r} is a clearance scope — grant it through the "
                "time-bound clearance path (bounded expiry + mandatory reason), "
                "not as a permanent scope",
                err=True,
            )
            raise typer.Exit(code=_EXIT_CLEARANCE_REFUSED)
        if scope not in _GRANTABLE:
            typer.echo(f"error: unknown scope {scope!r}", err=True)
            raise typer.Exit(code=_EXIT_USAGE)

    for scope in scopes:
        await storage.grant_scope(
            user_id=target.id,
            scope=scope,
            granted_at=now,
            granted_by_user_id=authorizer.id,
        )
    audit = _audit_emitter(storage)
    await audit.emit(
        event="eyenet.audit.auth.scopes.granted",
        subject_kind="system_user",
        subject_id=target.id,
        system_user_id=authorizer.id,
        payload={"username": username, "scopes": list(scopes)},
    )
    await _publish_scopes_changed(cfg, target.id)
    typer.echo(f"granted to {username!r}: {', '.join(scopes)}")


@scopes_app.command("revoke")
def scopes_revoke(
    username: str = typer.Argument(..., help="System-user username."),
    scopes: list[str] = typer.Argument(..., help="One or more scopes to revoke."),
    as_user: str = typer.Option(..., "--as", help="Authorizer username (must hold admin:users)."),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Revoke explicit scope grants from a user (baseline scopes are untouched)."""
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_scopes_revoke(storage, cfg, username=username, scopes=scopes, as_user=as_user))


async def _scopes_revoke(
    storage: BaseRepository,
    cfg: RuntimeConfig,
    *,
    username: str,
    scopes: list[str],
    as_user: str,
) -> None:
    now = datetime.now(tz=UTC)
    authorizer = await _authorize(
        storage, cfg.data_dir, actor_username=as_user, require_scope=_ADMIN_USERS_SCOPE, now=now
    )
    target = await storage.get_system_user_by_username(username)
    if target is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)

    revoked: list[str] = []
    for scope in scopes:
        try:
            await storage.revoke_scope(user_id=target.id, scope=scope)
        except ValueError:
            typer.echo(f"warning: {scope!r} was not an explicit grant on {username!r}", err=True)
            continue
        revoked.append(scope)

    if revoked:
        audit = _audit_emitter(storage)
        await audit.emit(
            event="eyenet.audit.auth.scopes.revoked",
            subject_kind="system_user",
            subject_id=target.id,
            system_user_id=authorizer.id,
            payload={"username": username, "scopes": revoked},
        )
        await _publish_scopes_changed(cfg, target.id)
    typer.echo(f"revoked from {username!r}: {', '.join(revoked) if revoked else '(none)'}")


@scopes_app.command("list")
def scopes_list(
    username: str = typer.Argument(..., help="System-user username."),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """List a user's role baseline and explicit scope grants (read-only)."""
    cfg = RuntimeConfig.from_env(data_dir=data_dir)
    storage = get_repository(data_dir=cfg.data_dir)
    asyncio.run(_scopes_list(storage, username=username))


async def _scopes_list(storage: BaseRepository, *, username: str) -> None:
    target = await storage.get_system_user_by_username(username)
    if target is None:
        typer.echo(f"error: unknown user {username!r}", err=True)
        raise typer.Exit(code=_EXIT_USAGE)
    explicit = await storage.list_explicit_scopes(target.id)
    baseline = sorted(ROLE_BASELINE[target.role])
    typer.echo(f"{username} (role={target.role.value})")
    typer.echo(f"  baseline: {', '.join(baseline)}")
    if explicit:
        typer.echo("  explicit grants:")
        for row in explicit:
            typer.echo(f"    {row.scope}  (granted_at={row.granted_at.isoformat()})")
    else:
        typer.echo("  explicit grants: (none)")


__all__ = ["user_app"]
