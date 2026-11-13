# SPDX-License-Identifier: AGPL-3.0-or-later
"""ROLE_BASELINE + per-request effective-scope resolver.

API_PLAN §4.6 — baseline is a frozen mapping in code (not configuration)
so the entire policy is reviewable in one diff and cannot drift via
runtime config changes. Grant-only scopes (read:restricted,
read:classified, admin:reclassify, admin:case, admin:clearance,
write:panic, admin:sources, read:collectors_config, admin:collectors,
admin:candidates) are NEVER in any baseline.

Permanent CAPABILITY scopes that gate a whole subsystem (``GRANT_ONLY_CAPABILITIES``,
e.g. write:stealer) are likewise never in a baseline, but unlike clearance scopes
they do not expire — they persist until revoked, for service/operator identities
whose access cannot ride a bounded clearance grant (the 24/7 collector).
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
            "read:search",
            "write:graph",
            "read:metrics",
            "read:cases",
            "write:actors",
            "write:linkage_decision",
            "write:persona_decision",
            "write:identity",
            "write:cases",
            "write:documents",
            "read:sources",
            "write:sources",
            "read:collectors",
            "write:collectors",
            "admin:collectors",
            "read:candidates",
            "write:candidates",
            "read:groups",
            "write:groups",
            "stream:linkages",
            "stream:personas",
            "stream:audit",
            "stream:control",
            "read:incidents",
            "write:incidents",
            "stream:incidents",
            "admin:incident_rules",
            "admin:users",
            "admin:tokens",
            "admin:settings",
            "proxy:read",
            "proxy:write",
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
            "read:search",
            "write:graph",
            "read:cases",
            "write:actors",
            "write:linkage_decision",
            "write:persona_decision",
            "write:identity",
            "write:cases",
            "write:documents",
            "read:sources",
            "write:sources",
            "read:collectors",
            "write:collectors",
            "read:candidates",
            "write:candidates",
            "read:groups",
            "write:groups",
            "stream:linkages",
            "stream:personas",
            "read:incidents",
            "write:incidents",
            "stream:incidents",
            "proxy:read",
            "proxy:write",
        },
    ),
    SystemUserRole.VIEWER: frozenset(
        {
            "read:actors",
            "read:personas",
            "read:linkages",
            "read:graph",
            "read:search",
            "read:incidents",
        },
    ),
}


# Permanent capability scopes gating a whole subsystem. Granted via
# SystemUserScopeTable (CLI `user scopes grant`) like baseline scopes, but NEVER in
# any baseline — no role auto-holds them; access is always an explicit, audited
# grant. Distinct from ClearanceScope (sensitive reads, EXPIRING): these gate
# service/operator CAPABILITY and PERSIST (the 24/7 collector's write:stealer cannot
# ride a 90-day clearance grant).
#
# `admin:clearance` is here (not a ClearanceScope) because it's the permanent authority
# to grant/revoke clearances — it must be CLI-grantable or the whole clearance system is
# un-bootstrappable (it gates POST /v1/clearance/grants, so a fresh admin self-grants it
# once via `user scopes grant`, then can issue read:stealer / read:restricted / … grants).
GRANT_ONLY_CAPABILITIES: frozenset[str] = frozenset(
    {"write:stealer", "admin:stealer", "admin:clearance", "proxy:admin"}
)


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


__all__ = ["GRANT_ONLY_CAPABILITIES", "ROLE_BASELINE", "resolve_effective_scopes"]
