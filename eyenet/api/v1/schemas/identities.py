"""Identity-pool action bodies + global panic body.

Every write returns `WriteAccepted` (see `writes.py`); only the input
bodies live here.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — IdentityActionRequest, PanicRequest.
API_PLAN §3.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from eyenet.contracts.collector import CollectorRow
from eyenet.contracts.enums import CollectorObservedState, IdentityRole, IdentityState
from eyenet.contracts.identity import IdentityRow

from ._base import ApiSchema
from .pagination import CursorPage


class IdentitySummary(ApiSchema):
    """List view of a pool identity (GET /v1/identities).

    OPSEC fields are intentionally omitted: ``session_path`` (filesystem path
    to the encrypted session blob) and ``proxy_uri`` (may embed credentials)
    never cross the read surface.
    """

    identity_id: UUID
    name: str
    source_id: UUID
    role: IdentityRole
    state: IdentityState
    last_used_at: datetime | None = None

    @classmethod
    def from_domain(cls, row: IdentityRow) -> IdentitySummary:
        return cls(
            identity_id=row.id,
            name=row.name,
            source_id=row.source_id,
            role=row.role,
            state=row.state,
            last_used_at=row.last_used_at,
        )


class IdentityDetail(IdentitySummary):
    """Detail view (GET /v1/identities/{id}) — same OPSEC omissions.

    Surfaces the forum collector's PACING profile so the operator can see what an
    identity's collector is actually running: the named evasion level (if one was
    chosen) and the resolved inter-request delay window. Non-secret config, read
    from ``source_config``; ``None`` for non-forum identities.
    """

    cooldown_seconds: int
    graduated_at: datetime | None = None
    notes: str | None = None
    # Editable collector config (non-secret source_config). Forum fields are None for a
    # non-forum identity; monitor_groups is the telegram knob. Secrets (api_hash, session
    # blob) are deliberately NOT surfaced.
    forum_base_url: str | None = None
    forum_thread_urls: list[str] = Field(default_factory=list)
    forum_engine: str | None = None
    forum_user_agent: str | None = None
    forum_evasion_level: str | None = None
    forum_delay_min: float | None = None
    forum_delay_max: float | None = None
    forum_discovery_depth: int | None = None
    forum_discovery_interval: int | None = None
    forum_max_category_pages: int | None = None
    forum_max_thread_pages: int | None = None
    forum_steady_pages: int | None = None
    forum_tls_impersonate: str | None = None
    forum_enable_waf_bypass: bool | None = None
    monitor_groups: list[str] = Field(default_factory=list)
    # The collector that reads this config (so the panel can restart it to apply changes).
    collector_id: UUID | None = None
    collector_observed_state: CollectorObservedState | None = None

    @classmethod
    def from_domain(cls, row: IdentityRow, collector: CollectorRow | None = None) -> IdentityDetail:
        cfg = row.source_config or {}
        return cls(
            identity_id=row.id,
            name=row.name,
            source_id=row.source_id,
            role=row.role,
            state=row.state,
            last_used_at=row.last_used_at,
            cooldown_seconds=row.cooldown_seconds,
            graduated_at=row.graduated_at,
            notes=row.notes,
            forum_base_url=cfg.get("forum_base_url"),
            forum_thread_urls=cfg.get("forum_thread_urls") or [],
            forum_engine=cfg.get("forum_engine"),
            forum_user_agent=cfg.get("forum_user_agent"),
            forum_evasion_level=cfg.get("forum_evasion_level"),
            forum_delay_min=cfg.get("forum_delay_min"),
            forum_delay_max=cfg.get("forum_delay_max"),
            forum_discovery_depth=cfg.get("forum_discovery_depth"),
            forum_discovery_interval=cfg.get("forum_discovery_interval"),
            forum_max_category_pages=cfg.get("forum_max_category_pages"),
            forum_max_thread_pages=cfg.get("forum_max_thread_pages"),
            forum_steady_pages=cfg.get("forum_steady_pages"),
            forum_tls_impersonate=cfg.get("forum_tls_impersonate"),
            forum_enable_waf_bypass=cfg.get("forum_enable_waf_bypass"),
            monitor_groups=cfg.get("monitor_groups") or [],
            collector_id=collector.id if collector is not None else None,
            collector_observed_state=collector.observed_state if collector is not None else None,
        )


class CursorPageIdentitySummary(CursorPage[IdentitySummary]):
    """200 page response for GET /v1/identities."""


class IdentityActionRequest(ApiSchema):
    """Body for `POST /v1/identities/{id}/{claim,release}` and `/freeze_all`."""

    reason: str = Field(min_length=1, max_length=1024)
    note: str | None = Field(default=None, max_length=4096)


class IdentityConfigUpdate(ApiSchema):
    """Body for `PATCH /v1/identities/{id}/config` — edit the non-secret collector config.

    Every field is optional; only fields actually sent are merged (``exclude_unset``). An
    empty string clears a clearable field (user_agent, tls_impersonate); a provided list
    replaces it. Load-bearing values (engine, evasion level, tls_impersonate) are validated
    server-side against the same registry create-identity uses.
    """

    # Forum
    forum_base_url: str | None = Field(default=None, max_length=1024)
    forum_thread_urls: list[str] | None = None
    forum_engine: str | None = Field(default=None, max_length=32)
    forum_user_agent: str | None = Field(default=None, max_length=512)
    forum_evasion_level: str | None = Field(default=None, max_length=32)
    forum_tls_impersonate: str | None = Field(default=None, max_length=64)
    forum_enable_waf_bypass: bool | None = None
    forum_delay_min: float | None = Field(default=None, ge=0)
    forum_delay_max: float | None = Field(default=None, ge=0)
    forum_discovery_interval: int | None = Field(default=None, ge=0)
    forum_max_category_pages: int | None = Field(default=None, ge=0)
    forum_max_thread_pages: int | None = Field(default=None, ge=0)
    forum_steady_pages: int | None = Field(default=None, ge=0)
    forum_discovery_depth: int | None = Field(default=None, ge=0)
    # Telegram
    monitor_groups: list[str] | None = None


class PanicRequest(ApiSchema):
    """Body for `POST /v1/panic` — global system halt.

    `confirm` is a mandatory blocking acknowledgment. The literal string
    `I_UNDERSTAND` must be present to prevent accidental panic from a
    stray curl.
    """

    reason: str = Field(min_length=1, max_length=1024)
    confirm: Literal["I_UNDERSTAND"]


__all__ = [
    "CursorPageIdentitySummary",
    "IdentityActionRequest",
    "IdentityDetail",
    "IdentitySummary",
    "PanicRequest",
]
