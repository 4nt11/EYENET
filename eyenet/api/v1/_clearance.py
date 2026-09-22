# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clearance gate — tier -> read-scope enforcement for evidence surfaces (§4.6-4.8).

The one dispatch point for "may this caller see a row of this effective tier?".
Reused by the attachment manifest/access handlers, the document GET, and any
future byte-serving surface. Two entry points:

* :func:`enforce_tier_clearance` — pure scope check for a READ that appends no
  journal row (manifest, document metadata). NORMAL is open to any authenticated
  caller; RESTRICTED/CLASSIFIED require the matching ``read:*`` scope.
* :func:`resolve_tier_grant` — the same check PLUS resolution of the concrete
  active grant id, which the file-access journal REQUIRES on every non-NORMAL row
  (``_TIER_REQUIRES_GRANT_AND_ACK_CK``). Returns ``None`` for NORMAL.

Clearance grants are already folded into ``current_user.effective_scopes`` by the
auth cache (``resolve_effective_scopes``), so the scope check is set-membership.
The grant-id lookup hits storage only on the byte-serving path, where the audit
row must name the exact grant that authorised the access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.api.deps import ScopeForbidden
from eyenet.contracts.enums import ClearanceScope, SensitivityTier

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eyenet.api.deps import CurrentUser
    from eyenet.storage.repository import BaseRepository

# Exact per-tier scope. Higher clearance does NOT implicitly subsume lower here —
# whether a read:classified holder also gets read:restricted is decided upstream
# in resolve_effective_scopes; this table only maps a row's tier to the ONE scope
# that unlocks it. NORMAL maps to None (open to any authenticated caller).
_TIER_SCOPE: dict[SensitivityTier, ClearanceScope | None] = {
    SensitivityTier.NORMAL: None,
    SensitivityTier.RESTRICTED: ClearanceScope.READ_RESTRICTED,
    SensitivityTier.CLASSIFIED: ClearanceScope.READ_CLASSIFIED,
}


def required_clearance_scope(tier: SensitivityTier) -> ClearanceScope | None:
    """The clearance scope that unlocks ``tier``, or ``None`` for NORMAL."""
    return _TIER_SCOPE[tier]


def enforce_tier_clearance(current_user: CurrentUser, effective_tier: SensitivityTier) -> None:
    """Raise :class:`ScopeForbidden` (403) if the caller may not read ``effective_tier``.

    Fail-closed: an unknown tier is not in the table and raises ``KeyError`` at the
    boundary rather than silently passing. NORMAL always passes.
    """
    needed = _TIER_SCOPE[effective_tier]
    if needed is not None and needed.value not in current_user.effective_scopes:
        raise ScopeForbidden(needed.value)


async def resolve_tier_grant(
    current_user: CurrentUser,
    storage: BaseRepository,
    effective_tier: SensitivityTier,
    *,
    now: datetime | None = None,
) -> UUID | None:
    """Enforce the read scope AND resolve the active grant id for the journal row.

    Returns ``None`` for NORMAL (no grant required). For RESTRICTED/CLASSIFIED,
    enforces the scope, then resolves a live (non-revoked, non-expired) grant of
    the matching scope. A cache/grant race — scope present in ``effective_scopes``
    but no live grant — fails CLOSED with 403. When multiple grants match, the
    longest-lived (latest ``expires_at``) is attributed on the journal row.
    """
    needed = _TIER_SCOPE[effective_tier]
    if needed is None:
        return None
    if needed.value not in current_user.effective_scopes:
        raise ScopeForbidden(needed.value)
    grants = [
        g
        for g in await storage.active_clearance_grants_for(current_user.user_id, now=now)
        if g.scope is needed
    ]
    if not grants:
        # effective_scopes carried the scope (cache tick) but no live grant remains.
        raise ScopeForbidden(needed.value)
    return max(grants, key=lambda g: g.expires_at).id


async def resolve_scope_grant(
    current_user: CurrentUser,
    storage: BaseRepository,
    scope: ClearanceScope,
    *,
    now: datetime | None = None,
) -> UUID | None:
    """Resolve the active (non-revoked, non-expired) grant id for ``scope``, or None.

    Used where the concrete grant id is needed for an audit row (e.g. the §4.9
    ``admin:reclassify`` authority). Returns the longest-lived matching grant's
    id, or ``None`` when the caller holds no live grant for the scope; the caller
    decides the failure response.
    """
    grants = [
        g
        for g in await storage.active_clearance_grants_for(current_user.user_id, now=now)
        if g.scope is scope
    ]
    if not grants:
        return None
    return max(grants, key=lambda g: g.expires_at).id


__all__ = [
    "enforce_tier_clearance",
    "required_clearance_scope",
    "resolve_scope_grant",
    "resolve_tier_grant",
]
