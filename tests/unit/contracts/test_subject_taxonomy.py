"""PLAN §3 — every exported SUBJECT must match the documented taxonomy."""

from __future__ import annotations

import re

import pytest

from eyenet.contracts import attribution, audit, identity, observation, raw_message

# Allowed subject patterns from PLAN §3. We accept either a concrete subject
# or a pattern containing `{placeholder}` segments / `>` wildcard tail.
_ALLOWED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"^raw\.message\.\{source\}\.\{instance_id\}$",
        r"^actor\.observation\.text\.>$",
        r"^identity\.label\.applied$",
        r"^identity\.engagement\.authorized$",
        r"^attribution\.profile\.candidate$",
        r"^attribution\.profile\.current$",
        r"^attribution\.linkage\.proposed$",
        r"^eyenet\.audit\.>$",
    )
)


def _matches_allowed(subject: str) -> bool:
    return any(p.fullmatch(subject) for p in _ALLOWED_PATTERNS)


@pytest.mark.contract
def test_all_subjects_in_taxonomy() -> None:
    subjects = {
        "raw_message.SUBJECT": raw_message.SUBJECT,
        "observation.SUBJECT": observation.SUBJECT,
        "identity.SUBJECT_LABEL": identity.SUBJECT_LABEL,
        "identity.SUBJECT_ENGAGEMENT": identity.SUBJECT_ENGAGEMENT,
        "attribution.SUBJECT_PROFILE_CANDIDATE": attribution.SUBJECT_PROFILE_CANDIDATE,
        "attribution.SUBJECT_PROFILE_CURRENT": attribution.SUBJECT_PROFILE_CURRENT,
        "attribution.SUBJECT_LINKAGE_PROPOSED": attribution.SUBJECT_LINKAGE_PROPOSED,
        "audit.SUBJECT": audit.SUBJECT,
    }
    bad = {k: v for k, v in subjects.items() if not _matches_allowed(v)}
    assert not bad, f"subjects outside PLAN §3 taxonomy: {bad}"


@pytest.mark.contract
def test_raw_message_subject_renders() -> None:
    rendered = raw_message.subject_for("telegram", "abcd1234")
    assert rendered == "raw.message.telegram.abcd1234"


@pytest.mark.contract
def test_audit_subject_renders() -> None:
    assert audit.subject_for("engine") == "eyenet.audit.engine"
