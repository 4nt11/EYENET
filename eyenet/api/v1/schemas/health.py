"""Liveness and readiness probe bodies.

`/v1/healthz` returns `HealthStatus`; `/v1/readyz` returns `ReadyStatus`
(200 when every component is up, 503 problem+json otherwise — same shape
serialized via the standard error envelope).

OpenAPI: `contracts/openapi/eyenet.v1.yaml#/components/schemas/{HealthStatus,ReadyStatus}`
API_PLAN §3.6.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import ApiSchema


class HealthStatus(ApiSchema):
    """Process-up liveness signal."""

    status: Literal["ok"] = Field(description="Always `ok` when the process is reachable.")


class ReadyComponents(ApiSchema):
    """Per-subsystem readiness flags surfaced from `/v1/readyz`."""

    storage: Literal["up", "down"]
    bus: Literal["up", "down"]
    auth_keys: Literal["up", "down"]


class ReadyStatus(ApiSchema):
    """Aggregate readiness — storage open, bus subscribed, auth keys loaded."""

    status: Literal["ready", "degraded"]
    components: ReadyComponents


__all__ = ["HealthStatus", "ReadyComponents", "ReadyStatus"]
