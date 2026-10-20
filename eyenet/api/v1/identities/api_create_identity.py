# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/identities — provision an identity from an uploaded session file.

Multipart upload of a credential (Telegram: a ``.session`` file) plus its
non-secret config. The secret is converted, Fernet-encrypted, and written to
disk mode 0600 by :func:`eyenet.identity_pool._provision.provision_identity`;
the plaintext never persists server-side and never crosses the read surface.

Gated on ``write:identity`` AND the admin role: creating a credential is the
single most dangerous identity write, so it is admin-only even though the
lifecycle actions (claim/freeze/burn) accept any ``write:identity`` holder.
Creation is synchronous (there is no async settle step), so this returns 201
with the ``IdentityDetail`` — unlike the 202 action writes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    ScopeForbidden,
    get_audit,
    get_data_dir,
    get_session_key,
    get_storage,
)
from eyenet.api.v1.schemas.identities import IdentityDetail
from eyenet.collectors.forum import get_parser
from eyenet.collectors.forum._timing_presets import (
    FORUM_TLS_IMPERSONATE_TARGETS,
    resolve_evasion_profile,
)
from eyenet.contracts.enums import IdentityRole, SourceKind, SystemUserRole
from eyenet.contracts.source import SourceRow
from eyenet.identity_pool._provision import SessionValidationError, provision_identity
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["identities"])

# A Telethon .session is a small SQLite file (tens of KB). Cap generously to
# reject a mistaken bulk upload without truncating a legitimate session.
_MAX_SESSION_BYTES = 1 * 1024 * 1024


@router.post(
    "/identities",
    operation_id="identities_create",
    response_model=IdentityDetail,
    status_code=201,
)
async def identities_create(
    current_user: Annotated[CurrentUser, Depends(RequireScope("write:identity"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    session_key: Annotated[object, Depends(get_session_key)],
    session: Annotated[
        UploadFile, File(description="the credential file (Telegram .session or forum cookies.txt)")
    ],
    name: Annotated[str, Form(min_length=1, max_length=128)],
    source_id: Annotated[UUID, Form()],
    telegram_api_id: Annotated[int | None, Form()] = None,
    telegram_api_hash: Annotated[str | None, Form(max_length=256)] = None,
    monitor_groups: Annotated[str | None, Form(description="comma-separated")] = None,
    forum_base_url: Annotated[str | None, Form(max_length=1024)] = None,
    forum_thread_urls: Annotated[
        str | None, Form(description="comma-separated thread URLs")
    ] = None,
    forum_engine: Annotated[
        str | None, Form(max_length=32, description="board engine: mybb (default) | xenforo")
    ] = None,
    forum_user_agent: Annotated[
        str | None,
        Form(max_length=1024, description="UA of the browser that minted the cookie jar"),
    ] = None,
    forum_evasion_level: Annotated[
        str | None,
        Form(max_length=16, description="ghost|lurker|regular|brisk|smash (E0..E4); sets pacing"),
    ] = None,
    forum_tls_impersonate: Annotated[
        str | None,
        Form(
            max_length=64,
            description="curl-cffi Firefox target for a clearnet WAF board (e.g. firefox147)",
        ),
    ] = None,
    forum_enable_waf_bypass: Annotated[
        bool,
        Form(description="route via FlareSolverr to clear a CF JS challenge + Anubis PoW"),
    ] = False,
    discord_impersonate: Annotated[
        str | None,
        Form(max_length=64, description="curl-cffi target matching the token's browser"),
    ] = None,
    discord_user_agent: Annotated[str | None, Form(max_length=1024)] = None,
    discord_delay_min: Annotated[float | None, Form(ge=0)] = None,
    discord_delay_max: Annotated[float | None, Form(ge=0)] = None,
    discord_enable_waf_bypass: Annotated[
        bool, Form(description="remint cf_clearance via FlareSolverr (default on for Discord)")
    ] = True,
    cooldown_seconds: Annotated[int, Form(ge=0)] = 21_600,
    proxy_uri: Annotated[str | None, Form(max_length=1024)] = None,
    role: Annotated[IdentityRole, Form()] = IdentityRole.MONITOR,
    notes: Annotated[str | None, Form(max_length=4096)] = None,
) -> IdentityDetail:
    if current_user.role != SystemUserRole.ADMIN:
        raise ScopeForbidden("admin (identity provisioning is admin-only)")

    source = await storage.get_source(source_id)
    if not isinstance(source, SourceRow):
        raise ResourceNotFound("source")
    source_kind = SourceKind(source.kind)

    blob = await session.read()
    if len(blob) > _MAX_SESSION_BYTES:
        raise HTTPException(status_code=413, detail="session file too large")

    source_config = _build_source_config(
        source_kind,
        telegram_api_id=telegram_api_id,
        telegram_api_hash=telegram_api_hash,
        monitor_groups=monitor_groups,
        forum_base_url=forum_base_url,
        forum_thread_urls=forum_thread_urls,
        forum_engine=forum_engine,
        forum_user_agent=forum_user_agent,
        forum_evasion_level=forum_evasion_level,
        forum_tls_impersonate=forum_tls_impersonate,
        forum_enable_waf_bypass=forum_enable_waf_bypass,
        discord_impersonate=discord_impersonate,
        discord_user_agent=discord_user_agent,
        discord_delay_min=discord_delay_min,
        discord_delay_max=discord_delay_max,
        discord_enable_waf_bypass=discord_enable_waf_bypass,
    )

    try:
        row = await provision_identity(
            storage=storage,
            session_key=session_key,  # type: ignore[arg-type]  # Fernet (deps returns object)
            data_dir=data_dir,
            name=name,
            source_id=source_id,
            source_kind=source_kind,
            secret_blob=blob,
            source_config=source_config,
            role=role,
            cooldown_seconds=cooldown_seconds,
            proxy_uri=proxy_uri,
            notes=notes,
        )
    except SessionValidationError as exc:
        raise RequestValidationError(
            [{"loc": ("body", "session"), "msg": str(exc), "type": "value_error"}]
        ) from exc

    await audit.emit(
        event="identity.provisioned",
        subject_kind="identity",
        subject_id=row.id,
        system_user_id=current_user.user_id,
        payload={
            "name": row.name,
            "source_id": str(source_id),
            "source_kind": source_kind.value,
            "session_sha256": hashlib.sha256(blob).hexdigest(),
        },
    )
    return IdentityDetail.from_domain(row)


def _build_source_config(  # noqa: PLR0912  (per-source dispatcher; branches are inherent)
    source_kind: SourceKind,
    *,
    telegram_api_id: int | None,
    telegram_api_hash: str | None,
    monitor_groups: str | None,
    forum_base_url: str | None = None,
    forum_thread_urls: str | None = None,
    forum_engine: str | None = None,
    forum_user_agent: str | None = None,
    forum_evasion_level: str | None = None,
    forum_tls_impersonate: str | None = None,
    forum_enable_waf_bypass: bool = False,
    discord_impersonate: str | None = None,
    discord_user_agent: str | None = None,
    discord_delay_min: float | None = None,
    discord_delay_max: float | None = None,
    discord_enable_waf_bypass: bool = True,
) -> dict[str, object]:
    """Assemble the non-secret per-source config, keyed by IdentityFileEntry field
    names so the pool can splat it back into an entry. New sources add a branch."""
    if source_kind == SourceKind.TELEGRAM:
        if telegram_api_id is None or telegram_api_hash is None:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "telegram_api_id"),
                        "msg": "telegram_api_id and telegram_api_hash are required for Telegram",
                        "type": "value_error",
                    }
                ]
            )
        groups = [g.strip() for g in (monitor_groups or "").split(",") if g.strip()]
        return {
            "telegram_api_id": telegram_api_id,
            "telegram_api_hash": telegram_api_hash,
            "monitor_groups": groups,
        }
    if source_kind == SourceKind.FORUM:
        if not forum_base_url:
            raise RequestValidationError(
                [
                    {
                        "loc": ("body", "forum_base_url"),
                        "msg": "forum_base_url is required for Forum",
                        "type": "value_error",
                    }
                ]
            )
        urls = [u.strip() for u in (forum_thread_urls or "").split(",") if u.strip()]
        config: dict[str, object] = {"forum_base_url": forum_base_url, "forum_thread_urls": urls}
        # Board engine selects the parser. Validate against the registry so a typo
        # fails here, not with silent empty parses at crawl time. Omitted → MyBB.
        if forum_engine:
            try:
                get_parser(forum_engine)
            except ValueError as exc:
                raise RequestValidationError(
                    [{"loc": ("body", "forum_engine"), "msg": str(exc), "type": "value_error"}]
                ) from exc
            config["forum_engine"] = forum_engine.strip().lower()
        # Optional: the UA of the browser that minted the cookie jar (Tor Browser
        # for an .onion board). Omitted → the collector's TB default. Only emit
        # when set so the pool's entry keeps its own default otherwise.
        if forum_user_agent:
            config["forum_user_agent"] = forum_user_agent
        # Evasion level is a preset: expand it to the concrete knobs the collector
        # reads (pacing + subforum-discovery depth), and keep the level itself for
        # the record. Unknown level → rejected (a typo shouldn't silently fall back).
        if forum_evasion_level:
            prof = resolve_evasion_profile(forum_evasion_level)
            if prof is None:
                raise RequestValidationError(
                    [
                        {
                            "loc": ("body", "forum_evasion_level"),
                            "msg": "unknown evasion level (ghost|lurker|regular|brisk|smash)",
                            "type": "value_error",
                        }
                    ]
                )
            config["forum_evasion_level"] = forum_evasion_level.strip().lower()
            config["forum_delay_min"] = prof.delay_min
            config["forum_delay_max"] = prof.delay_max
            config["forum_discovery_depth"] = prof.discovery_depth
        # curl-cffi TLS-impersonation target for a clearnet WAF board. Validate
        # against the allow-set (a typo must not silently ship an OpenSSL/bot
        # fingerprint) and keep the value in source_config for the collector.
        if forum_tls_impersonate:
            if forum_tls_impersonate not in FORUM_TLS_IMPERSONATE_TARGETS:
                raise RequestValidationError(
                    [
                        {
                            "loc": ("body", "forum_tls_impersonate"),
                            "msg": f"unknown impersonation target; allowed: "
                            f"{sorted(FORUM_TLS_IMPERSONATE_TARGETS)}",
                            "type": "value_error",
                        }
                    ]
                )
            config["forum_tls_impersonate"] = forum_tls_impersonate
        # WAF bypass: route via FlareSolverr (a real browser) for a CF JS challenge
        # + Anubis PoW. Only emit when enabled so the entry keeps its default (off).
        if forum_enable_waf_bypass:
            config["forum_enable_waf_bypass"] = True
        return config
    if source_kind == SourceKind.DISCORD:
        return _discord_source_config(
            impersonate=discord_impersonate,
            user_agent=discord_user_agent,
            delay_min=discord_delay_min,
            delay_max=discord_delay_max,
            enable_waf_bypass=discord_enable_waf_bypass,
        )
    raise RequestValidationError(
        [
            {
                "loc": ("body", "source_id"),
                "msg": f"identity upload not supported for source: {source_kind.value}",
                "type": "value_error",
            }
        ]
    )


def _discord_source_config(
    *,
    impersonate: str | None,
    user_agent: str | None,
    delay_min: float | None,
    delay_max: float | None,
    enable_waf_bypass: bool,
) -> dict[str, object]:
    """Non-secret Discord collector config (keyed by IdentityFileEntry fields). Secrets
    (token, cookie, X-Super-Properties, UA) ride in the uploaded JSON blob. WAF bypass
    defaults ON (Discord is always Cloudflare-fronted); impersonate MUST match the token's
    browser (operator-coherent, validated at connect)."""
    cfg: dict[str, object] = {"discord_enable_waf_bypass": enable_waf_bypass}
    if impersonate:
        cfg["discord_impersonate"] = impersonate
    if user_agent:
        cfg["discord_user_agent"] = user_agent
    if delay_min is not None:
        cfg["discord_delay_min"] = delay_min
    if delay_max is not None:
        cfg["discord_delay_max"] = delay_max
    return cfg
