"""Shape tests for `HealthStatus` + `ReadyStatus`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from eyenet.api.v1.schemas import HealthStatus, ReadyComponents, ReadyStatus

pytestmark = pytest.mark.contract


def test_health_status_happy() -> None:
    assert HealthStatus(status="ok").status == "ok"


@pytest.mark.parametrize("bad", ["OK", "alive", "ready", ""])
def test_health_status_rejects_other_literals(bad: str) -> None:
    with pytest.raises(PydanticValidationError):
        HealthStatus(status=bad)  # type: ignore[arg-type]


def test_ready_status_happy() -> None:
    rs = ReadyStatus(
        status="ready",
        components=ReadyComponents(storage="up", bus="up", auth_keys="up"),
    )
    assert rs.status == "ready"
    assert rs.components.storage == "up"


def test_ready_status_degraded_branch() -> None:
    rs = ReadyStatus.model_validate(
        {
            "status": "degraded",
            "components": {
                "storage": "down",
                "bus": "up",
                "auth_keys": "up",  # pragma: allowlist secret
            },
        },
    )
    assert rs.status == "degraded"
    assert rs.components.storage == "down"


def test_ready_status_rejects_unknown_component() -> None:
    with pytest.raises(PydanticValidationError):
        ReadyStatus.model_validate(
            {
                "status": "ready",
                "components": {
                    "storage": "up",
                    "bus": "up",
                    "auth_keys": "up",  # pragma: allowlist secret
                    "weird": "up",
                },
            },
        )


@pytest.mark.parametrize("missing", ["storage", "bus", "auth_keys"])
def test_ready_components_required(missing: str) -> None:
    payload = {"storage": "up", "bus": "up", "auth_keys": "up"}  # pragma: allowlist secret
    del payload[missing]
    with pytest.raises(PydanticValidationError):
        ReadyComponents.model_validate(payload)
