# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate + merge editable per-identity collector config (source_config).

The load-bearing forum fields (``forum_tls_impersonate``, evasion level, engine) are
validated against the SAME source of truth the create-identity path uses
(``FORUM_TLS_IMPERSONATE_TARGETS``, ``resolve_evasion_profile``, ``get_parser``) — a bad
value is a loud 422, never a silent fall back to an OpenSSL/bot fingerprint (CLAUDE.md
§4a). Merge semantics: only fields the client actually sent are touched; an empty string
clears a clearable string field; a provided list (even empty) replaces it.
"""

from __future__ import annotations

from typing import Any

from eyenet.api.deps import UnprocessableError
from eyenet.collectors.forum import get_parser
from eyenet.collectors.forum._timing_presets import (
    FORUM_TLS_IMPERSONATE_TARGETS,
    resolve_evasion_profile,
)
from eyenet.contracts.enums import SourceKind

# Fields the operator may edit, per source kind. Anything else in source_config
# (e.g. telegram_api_hash) is preserved untouched by the merge.
_FORUM_STR_CLEARABLE = ("forum_user_agent", "forum_tls_impersonate")
_FORUM_NUMERIC = (
    "forum_delay_min",
    "forum_delay_max",
    "forum_discovery_interval",
    "forum_max_category_pages",
    "forum_max_thread_pages",
    "forum_steady_pages",
    "forum_discovery_depth",
)


def _bad(field: str, msg: str) -> UnprocessableError:
    return UnprocessableError(f"{field}: {msg}")


def apply_config_updates(
    source_kind: SourceKind, existing: dict[str, Any], provided: dict[str, Any]
) -> dict[str, Any]:
    """Return a new source_config with ``provided`` (client-sent fields only) validated
    and merged over ``existing``. Raises :class:`UnprocessableError` on a bad value."""
    cfg = dict(existing)
    if source_kind is SourceKind.TELEGRAM:
        if "monitor_groups" in provided:
            groups = provided["monitor_groups"] or []
            cfg["monitor_groups"] = [str(g).strip() for g in groups if str(g).strip()]
        return cfg
    if source_kind is SourceKind.DISCORD:
        _apply_discord_updates(cfg, provided)
        return cfg
    if source_kind is not SourceKind.FORUM:
        raise _bad("source", f"config editing not supported for source: {source_kind.value}")
    _apply_forum_updates(cfg, provided)
    return cfg


# Discord editable pacing/fingerprint knobs. The impersonate target is a free string
# (curl_cffi validates it at collector boot); user_agent is clearable. The session blob
# (token/cookie/super_properties) is a SECRET edited via Replace credential, never here.
_DISCORD_STR_CLEARABLE = ("discord_impersonate", "discord_user_agent")
_DISCORD_NUMERIC = ("discord_delay_min", "discord_delay_max")


def _apply_discord_updates(cfg: dict[str, Any], provided: dict[str, Any]) -> None:
    """Validate + merge the discord editable fields into ``cfg`` in place."""
    for field in _DISCORD_STR_CLEARABLE:
        if field not in provided:
            continue
        val = (provided[field] or "").strip()
        if not val:
            cfg.pop(field, None)  # empty clears
        else:
            cfg[field] = val
    if "discord_enable_waf_bypass" in provided:
        cfg["discord_enable_waf_bypass"] = bool(provided["discord_enable_waf_bypass"])
    for field in _DISCORD_NUMERIC:
        if provided.get(field) is not None:
            if provided[field] < 0:
                raise _bad(field, "must be >= 0")
            cfg[field] = provided[field]
    if (
        "discord_delay_max" in cfg
        and cfg.get("discord_delay_min", 0) > cfg["discord_delay_max"]
    ):
        raise _bad("discord_delay_min", "must be <= discord_delay_max")


def _apply_forum_updates(cfg: dict[str, Any], provided: dict[str, Any]) -> None:
    """Validate + merge the forum editable fields into ``cfg`` in place."""
    if "forum_base_url" in provided:
        url = (provided["forum_base_url"] or "").strip()
        if not url:
            raise _bad("forum_base_url", "cannot be empty for a forum identity")
        cfg["forum_base_url"] = url
    if "forum_thread_urls" in provided:
        cfg["forum_thread_urls"] = [
            str(u).strip() for u in (provided["forum_thread_urls"] or []) if str(u).strip()
        ]
    if provided.get("forum_engine"):
        engine = str(provided["forum_engine"]).strip().lower()
        try:
            get_parser(engine)
        except ValueError as exc:
            raise _bad("forum_engine", str(exc)) from exc
        cfg["forum_engine"] = engine
    _apply_evasion_level(cfg, provided)  # first, so explicit numeric overrides below win
    _apply_clearable_strings(cfg, provided)
    if "forum_enable_waf_bypass" in provided:
        cfg["forum_enable_waf_bypass"] = bool(provided["forum_enable_waf_bypass"])
    for field in _FORUM_NUMERIC:
        if provided.get(field) is not None:
            if provided[field] < 0:
                raise _bad(field, "must be >= 0")
            cfg[field] = provided[field]
    if "forum_delay_max" in cfg and cfg.get("forum_delay_min", 0) > cfg["forum_delay_max"]:
        raise _bad("forum_delay_min", "must be <= forum_delay_max")


def _apply_evasion_level(cfg: dict[str, Any], provided: dict[str, Any]) -> None:
    """Expand the named evasion level to the concrete pacing + discovery knobs."""
    if "forum_evasion_level" not in provided:
        return
    level = (provided["forum_evasion_level"] or "").strip().lower()
    if not level:
        cfg.pop("forum_evasion_level", None)
        return
    prof = resolve_evasion_profile(level)
    if prof is None:
        raise _bad("forum_evasion_level", "unknown (ghost|lurker|regular|brisk|smash)")
    cfg["forum_evasion_level"] = level
    cfg["forum_delay_min"] = prof.delay_min
    cfg["forum_delay_max"] = prof.delay_max
    cfg["forum_discovery_depth"] = prof.discovery_depth


def _apply_clearable_strings(cfg: dict[str, Any], provided: dict[str, Any]) -> None:
    """user_agent / tls_impersonate: empty clears; tls_impersonate validated against the
    allow-set so a typo can't silently ship an OpenSSL/bot fingerprint (CLAUDE.md §4a)."""
    for field in _FORUM_STR_CLEARABLE:
        if field not in provided:
            continue
        val = (provided[field] or "").strip()
        if not val:
            cfg.pop(field, None)
        elif field == "forum_tls_impersonate" and val not in FORUM_TLS_IMPERSONATE_TARGETS:
            raise _bad(
                "forum_tls_impersonate",
                f"unknown target; allowed: {sorted(FORUM_TLS_IMPERSONATE_TARGETS)}",
            )
        else:
            cfg[field] = val
