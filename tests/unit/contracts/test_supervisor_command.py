# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pin the M9.E5 command-channel subject + new candidate audit subjects."""

from __future__ import annotations

import pytest

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.supervisor import JoinGroupCommand, command_subject_for

pytestmark = pytest.mark.unit


def test_command_subject_format() -> None:
    assert command_subject_for("abc12345") == "eyenet.control.collector.abc12345.command"
    # under the already-allowed control prefix
    assert command_subject_for("x").startswith("eyenet.control.")


def test_command_subject_matches_scout_instance_id() -> None:
    iid = compute_instance_id("scout_alpha", SourceKind.TELEGRAM)
    subject = command_subject_for(iid)
    assert iid in subject


def test_new_candidate_audit_subjects_exist() -> None:
    assert AuditSubject.CANDIDATE_JOINED.value == "eyenet.audit.candidate.joined"
    assert AuditSubject.CANDIDATE_FAILED.value == "eyenet.audit.candidate.failed"


def test_join_group_command_round_trips_json() -> None:
    from uuid import uuid4

    cmd = JoinGroupCommand(candidate_id=uuid4(), platform_groupid="@t", scout_identity_id=uuid4())
    restored = JoinGroupCommand.model_validate_json(cmd.model_dump_json())
    assert restored == cmd
