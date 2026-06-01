# SPDX-License-Identifier: AGPL-3.0-or-later
"""ROLE_BASELINE + per-request effective-scope resolver.

API_PLAN §4.6 — baseline is a frozen mapping in code (not configuration)
so the entire policy is reviewable in one diff and cannot drift via
runtime config changes. Grant-only scopes (read:restricted,
read:classified, admin:reclassify, admin:case, admin:clearance,
write:panic, admin:sources, read:collectors_config, admin:collectors,
admin:candidates) are NEVER in any baseline.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from eyenet.contracts.auth import SystemUserScopeRow
from eyenet.contracts.clearance import SystemUserClearanceGrantRow
from eyenet.contracts.enums import SystemUserRole
from eyenet.contracts.system_user import SystemUserRow

ROLE_BASELINE: Mapping[SystemUserRole, frozenset[str]] = {
    SystemUserRole.ADMIN: frozenset(
        {
            "read:actors",
            "read:personas",
            "read:linkages",
            "read:observations",
            "read:audit",
            "read:graph",
            "read:metrics",
            "read:cases",
            "write:linkage_decision",
            "write:identity",
            "write:cases",
            "write:documents",
            "read:sources",
            "write:sources",
            "read:collectors",
            "write:collectors",
            "read:candidates",
            "write:candidates",
            "stream:linkages",
            "stream:personas",
            "stream:audit",
            "stream:control",
            "admin:users",
            "admin:tokens",
        },
    ),
    SystemUserRole.ANALYST: frozenset(
        {
            "read:actors",
            "read:personas",
            "read:linkages",
            "read:observations",
            "read:audit",
            "read:graph",
            "read:cases",
            "write:linkage_decision",
            "write:identity",
            "write:cases",
            "write:documents",
            "read:sources",
            "write:sources",
            "read:collectors",
            "write:collectors",
            "read:candidates",
            "write:candidates",
            "stream:linkages",
            "stream:personas",
        },
    ),
    SystemUserRole.VIEWER: frozenset(
        {
            "read:actors",
            "read:personas",
            "read:linkages",
            "read:graph",
        },
    ),
}


def resolve_effective_scopes(
    user: SystemUserRow,
    explicit_grants: Iterable[SystemUserScopeRow],
    active_clearance_grants: Iterable[SystemUserClearanceGrantRow],
) -> frozenset[str]:
    """Pure: union baseline + explicit grants + active clearance scopes.

    Storage is authoritative: caller is responsible for filtering
    ``active_clearance_grants`` to the actually-active set
    (``granted_at <= now AND expires_at > now AND revoked_at IS NULL``)
    before passing in.
    """
    baseline = ROLE_BASELINE[user.role]
    explicit = {row.scope for row in explicit_grants}
    clearance = {grant.scope.value for grant in active_clearance_grants}
    return frozenset(baseline | explicit | clearance)


__all__ = ["ROLE_BASELINE", "resolve_effective_scopes"]
