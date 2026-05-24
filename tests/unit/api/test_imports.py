"""Smoke test: every public schema name imports cleanly.

Catches typos in `eyenet/api/v1/schemas/__init__.py` and missing
re-exports. The §14.4 OpenAPI-diff contract test (deferred to M9.0 when
FastAPI is wired) will replace this with a parity check against
`contracts/openapi/eyenet.v1.yaml`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.contract


def test_star_import_surfaces_every_name() -> None:
    import eyenet.api.v1.schemas as s

    # All names in __all__ resolve.
    for name in s.__all__:
        assert hasattr(s, name), f"declared in __all__ but missing: {name}"

    # No accidental leak of internal names through __all__.
    assert "ApiSchema" not in s.__all__
    assert "_label_or_synthesized" not in s.__all__


def test_expected_resource_groups_present() -> None:
    """Spot-check one schema per resource group so a missing import in
    `__init__.py` fails loud."""

    from eyenet.api.v1 import schemas

    expected = [
        "LoginRequest",  # auth
        "ActorSummary",  # actors
        "PersonaSummary",  # personas
        "LinkageSummary",  # linkages
        "GraphStats",  # graph
        "AuditRow",  # audit
        "IdentityActionRequest",  # identities
        "WriteAccepted",  # writes
        "LinkageProposedEvent",  # stream
        "HealthStatus",  # health
        "ProblemDetail",  # errors
        "CursorPage",  # pagination
        "StreamTopic",  # enums
    ]
    for name in expected:
        assert hasattr(schemas, name), name
