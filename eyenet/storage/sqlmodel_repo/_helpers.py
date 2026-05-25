# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared helpers for :class:`SQLModelRepository` mixins.

  * :func:`safe_session` — cancellation-safe :class:`AsyncSession`
    context manager used by every mixin
  * :data:`TIER_RANK` / :data:`RANK_TIER` — :class:`SensitivityTier`
    ordering used by monotonicity guards
  * :func:`new_audit_id`, :func:`build_audit_row` — audit-row dict
    constructor so the shape lives in one place
  * :func:`audit_or_warn` — cross-engine inconsistency breadcrumb;
    persists an audit row, syslog-WARNs on failure, re-raises
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid_extensions import uuid7

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import SensitivityTier, SystemLogLevel

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository


TIER_RANK: dict[SensitivityTier, int] = {
    SensitivityTier.NORMAL: 0,
    SensitivityTier.RESTRICTED: 1,
    SensitivityTier.CLASSIFIED: 2,
}
RANK_TIER: dict[int, SensitivityTier] = {v: k for k, v in TIER_RANK.items()}


@contextlib.asynccontextmanager
async def safe_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Cancellation-safe AsyncSession context manager.

    Rolls back on any exception (including ``asyncio.CancelledError``)
    before closing the session, so a cancelled task cannot leave a
    half-applied transaction lingering on the connection pool.
    """

    session = factory()
    try:
        yield session
    except BaseException:
        with contextlib.suppress(Exception):
            await session.rollback()
        raise
    finally:
        await session.close()


def new_audit_id() -> UUID:
    return UUID(str(uuid7()))


def build_audit_row(
    *,
    event: AuditSubject,
    actor: UUID | None,
    subject_kind: str,
    subject_id: UUID | None,
    payload: dict[str, Any],
    at: datetime,
    service: str,
    instance_id: str,
    trace_id: str | None,
    span_id: str | None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "id": new_audit_id(),
        "event": event.value,
        "service": service,
        "instance_id": instance_id,
        "system_user_id": actor,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "evidence_ref": evidence_ref,
        "trace_id": trace_id,
        "span_id": span_id,
        "payload": payload,
        "at": at,
    }


async def audit_or_warn(
    repo: BaseRepository,
    row: dict[str, Any],
    *,
    helper: str,
    domain_id: UUID | None = None,
) -> None:
    """Append the audit row; on failure WARN to syslog and re-raise.

    Domain writes commit first; this call lands the audit row second.
    When the audit append fails after a successful domain commit, the
    syslog WARN carries every breadcrumb an operator needs to
    reconcile: helper name, intended event, audit id, orphaned
    domain id.
    """

    try:
        await repo.append_audit(row)
    except Exception as exc:
        with contextlib.suppress(Exception):
            await repo.append_syslog(
                level=SystemLogLevel.WARN,
                service=row.get("service", "unknown"),
                instance_id=row.get("instance_id", "unknown"),
                event="audit.append_failed",
                message=(
                    f"audit append failed after domain commit "
                    f"(helper={helper}, event={row.get('event')})"
                ),
                error_type=type(exc).__name__,
                error_message=str(exc),
                fields={
                    "helper": helper,
                    "event": row.get("event"),
                    "audit_id": str(row.get("id")),
                    "domain_id": str(domain_id) if domain_id else None,
                    "subject_kind": row.get("subject_kind"),
                    "subject_id": (str(row["subject_id"]) if row.get("subject_id") else None),
                },
            )
        raise


__all__ = [
    "RANK_TIER",
    "TIER_RANK",
    "audit_or_warn",
    "build_audit_row",
    "new_audit_id",
    "safe_session",
]
