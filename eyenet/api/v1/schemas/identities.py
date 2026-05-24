"""Identity-pool action bodies + global panic body.

Every write returns `WriteAccepted` (see `writes.py`); only the input
bodies live here.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — IdentityActionRequest, PanicRequest.
API_PLAN §3.4.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ._base import ApiSchema


class IdentityActionRequest(ApiSchema):
    """Body for `POST /v1/identities/{id}/{claim,release}` and `/freeze_all`."""

    reason: str = Field(min_length=1, max_length=1024)
    note: str | None = Field(default=None, max_length=4096)


class PanicRequest(ApiSchema):
    """Body for `POST /v1/panic` — global system halt.

    `confirm` is a mandatory blocking acknowledgment. The literal string
    `I_UNDERSTAND` must be present to prevent accidental panic from a
    stray curl.
    """

    reason: str = Field(min_length=1, max_length=1024)
    confirm: Literal["I_UNDERSTAND"]


__all__ = ["IdentityActionRequest", "PanicRequest"]
