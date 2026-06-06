# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for select_access_artifact — the pure E5.5 selection policy.

The integration coupling (dispatch wiring) lives in
tests/integration/services/test_supervisor.py; this file pins the ranking /
filtering logic in isolation, no storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from eyenet.contracts.access_artifact import GroupAccessArtifactRow
from eyenet.contracts.enums import (
    ArtifactSubjectKind,
    ArtifactValidationState,
    GroupAccessKind,
)
from eyenet.services.collector_supervisor import select_access_artifact

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 6, tzinfo=UTC)


def _artifact(
    *,
    kind: GroupAccessKind,
    validation_state: ArtifactValidationState = ArtifactValidationState.UNVERIFIED,
    requires_admin_approval: bool = False,
    artifact_id: UUID | None = None,
) -> GroupAccessArtifactRow:
    return GroupAccessArtifactRow(
        id=artifact_id or UUID(int=1),
        subject_kind=ArtifactSubjectKind.CANDIDATE,
        candidate_id=UUID(int=99),
        kind=kind,
        value="https://t.me/+x",
        discovered_at_ingest=_NOW,
        validation_state=validation_state,
        requires_admin_approval=requires_admin_approval,
    )


def test_empty_returns_none() -> None:
    assert select_access_artifact([]) is None


def test_picks_cheapest_kind() -> None:
    invite = _artifact(kind=GroupAccessKind.INVITE_LINK, artifact_id=UUID(int=2))
    public = _artifact(kind=GroupAccessKind.PUBLIC_IDENTIFIER, artifact_id=UUID(int=3))
    chosen = select_access_artifact([invite, public])
    assert chosen is not None
    assert chosen.kind is GroupAccessKind.PUBLIC_IDENTIFIER


def test_skips_unusable_validation_states() -> None:
    for bad in (
        ArtifactValidationState.EXPIRED,
        ArtifactValidationState.REVOKED,
        ArtifactValidationState.USAGE_EXHAUSTED,
        ArtifactValidationState.BLOCKED_FOR_OUR_IDENTITY,
        ArtifactValidationState.UNKNOWN_FAILURE,
    ):
        art = _artifact(kind=GroupAccessKind.INVITE_LINK, validation_state=bad)
        assert select_access_artifact([art]) is None


def test_valid_and_unverified_are_usable() -> None:
    for ok in (ArtifactValidationState.VALID, ArtifactValidationState.UNVERIFIED):
        art = _artifact(kind=GroupAccessKind.INVITE_LINK, validation_state=ok)
        assert select_access_artifact([art]) is not None


def test_skips_admin_approval_required() -> None:
    art = _artifact(kind=GroupAccessKind.INVITE_LINK, requires_admin_approval=True)
    assert select_access_artifact([art]) is None


def test_skips_unsupported_kinds() -> None:
    for kind in (
        GroupAccessKind.QR_CODE,
        GroupAccessKind.DIRECT_INVITE,
        GroupAccessKind.PAID_SUBSCRIPTION,
        GroupAccessKind.ACCESS_BLOCKED,
        GroupAccessKind.RESTRICTED_OTHER,
    ):
        assert select_access_artifact([_artifact(kind=kind)]) is None


def test_tie_broken_deterministically_by_id() -> None:
    low = _artifact(kind=GroupAccessKind.INVITE_LINK, artifact_id=UUID(int=10))
    high = _artifact(kind=GroupAccessKind.INVITE_LINK, artifact_id=UUID(int=20))
    # same kind → smaller id wins, regardless of input order
    assert select_access_artifact([high, low]) is low
    assert select_access_artifact([low, high]) is low
