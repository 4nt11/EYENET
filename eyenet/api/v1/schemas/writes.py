"""Shared 202 Accepted response shape for every operator write.

All writes return 202 with a `WriteAccepted` body — the bus subject the
event will fan out on, the durable audit row's event id, an
`applied: false` flag (clients poll for true), and a poll URL.

OpenAPI: `contracts/openapi/eyenet.v1.yaml#/components/schemas/WriteAccepted`
API_PLAN §10.3.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from ._base import ApiSchema


class WriteAccepted(ApiSchema):
    """Common 202 envelope for `/v1/linkages/*/{confirm,reject,suspect}`,
    `/v1/identities/*/{claim,release}`, `/v1/identities/freeze_all`, and `/v1/panic`."""

    subject: str = Field(
        max_length=128,
        description="Bus subject the event will be published on.",
    )
    event_id: UUID = Field(description="Durable audit row id of the operator decision.")
    applied: bool = Field(
        description=(
            "Always False on the first response — bus fan-out is async. Clients "
            "poll `poll` URL or watch the relevant SSE stream to see the change land."
        ),
    )
    poll: str = Field(
        max_length=2048,
        description="Absolute or relative URL the client can GET to inspect current state.",
    )


__all__ = ["WriteAccepted"]
