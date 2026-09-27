# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for the incident-rule CRUD endpoints: projection + validation."""

from __future__ import annotations

from typing import Any

from eyenet.api.deps import ConflictError, UnprocessableError
from eyenet.api.v1.schemas.incidents import IncidentRuleOut
from eyenet.incidents import rules

WRITE_SCOPE = "admin:incident_rules"


def rule_out(row: Any) -> IncidentRuleOut:
    return IncidentRuleOut(
        id=row.id,
        name=row.name,
        pattern=row.pattern,
        label=row.label,
        weight=row.weight,
        enabled=row.enabled,
        description=row.description,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def validate_pattern_and_label(pattern: str, label: str) -> None:
    err = rules.validate_pattern(pattern)
    if err is not None:
        raise UnprocessableError(f"invalid RE2 pattern: {err}")
    if label not in rules.TAXONOMY_LABELS:
        raise UnprocessableError(f"label must be one of {sorted(rules.TAXONOMY_LABELS)}")


def validate_name(name: str) -> None:
    if name in rules.BUILTIN_SIGNAL_NAMES:
        raise ConflictError(f"name {name!r} collides with a built-in prefilter signal")
