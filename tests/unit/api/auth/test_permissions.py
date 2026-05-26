# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for eyenet.api.auth._permissions — ROLE_BASELINE + resolver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from eyenet.api.auth._permissions import ROLE_BASELINE, resolve_effective_scopes
from eyenet.contracts.auth import SystemUserScopeRow
from eyenet.contracts.clearance import SystemUserClearanceGrantRow
from eyenet.contracts.enums import ClearanceScope, SystemUserRole
from eyenet.contracts.system_user import SystemUserRow

_NOW = datetime(2026, 5, 26, tzinfo=UTC)


def _user(role: SystemUserRole) -> SystemUserRow:
    return SystemUserRow(
        id=uuid4(),
        username="op",
        display_name="Op",
        role=role,
        created_at=_NOW,
    )


def _grant(scope: ClearanceScope, user_id) -> SystemUserClearanceGrantRow:
    return SystemUserClearanceGrantRow(
        id=uuid4(),
        user_id=user_id,
        scope=scope,
        granted_by_user_id=uuid4(),
        reason="urgent forensic review — bench order #42",
        granted_at=_NOW,
        expires_at=_NOW + timedelta(days=30),
    )


def _explicit(scope: str, user_id) -> SystemUserScopeRow:
    return SystemUserScopeRow(
        user_id=user_id,
        scope=scope,
        granted_at=_NOW,
        granted_by_user_id=uuid4(),
    )


@pytest.mark.unit
def test_role_baseline_admin_includes_admin_tokens() -> None:
    assert "admin:tokens" in ROLE_BASELINE[SystemUserRole.ADMIN]


@pytest.mark.unit
def test_role_baseline_analyst_lacks_admin_users() -> None:
    assert "admin:users" not in ROLE_BASELINE[SystemUserRole.ANALYST]


@pytest.mark.unit
def test_role_baseline_viewer_is_strict_subset_of_analyst() -> None:
    assert ROLE_BASELINE[SystemUserRole.VIEWER] < ROLE_BASELINE[SystemUserRole.ANALYST]


@pytest.mark.parametrize(
    "scope",
    ["read:restricted", "read:classified", "admin:reclassify", "admin:case", "admin:clearance"],
)
@pytest.mark.unit
def test_grant_only_scopes_never_in_any_baseline(scope: str) -> None:
    for role_set in ROLE_BASELINE.values():
        assert scope not in role_set


@pytest.mark.unit
def test_resolve_baseline_only() -> None:
    user = _user(SystemUserRole.VIEWER)
    scopes = resolve_effective_scopes(user, [], [])
    assert scopes == ROLE_BASELINE[SystemUserRole.VIEWER]


@pytest.mark.unit
def test_resolve_unions_explicit_and_clearance() -> None:
    user = _user(SystemUserRole.VIEWER)
    explicit = [_explicit("read:metrics", user.id)]
    clearance = [_grant(ClearanceScope.READ_RESTRICTED, user.id)]
    scopes = resolve_effective_scopes(user, explicit, clearance)
    assert "read:metrics" in scopes
    assert "read:restricted" in scopes
    # baseline still present
    assert "read:actors" in scopes


@pytest.mark.unit
def test_resolve_never_intersects() -> None:
    # An empty explicit + clearance must not shrink baseline.
    user = _user(SystemUserRole.ANALYST)
    scopes = resolve_effective_scopes(user, [], [])
    assert scopes == ROLE_BASELINE[SystemUserRole.ANALYST]


@pytest.mark.unit
def test_analyst_does_not_get_admin_reclassify_from_baseline() -> None:
    user = _user(SystemUserRole.ANALYST)
    scopes = resolve_effective_scopes(user, [], [])
    assert "admin:reclassify" not in scopes
