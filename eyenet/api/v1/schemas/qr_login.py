# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request/response bodies for the QR-login provisioning flow.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — QrLoginStartRequest,
QrLoginChallenge, QrLoginStatusResponse, QrPasswordRequest.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from eyenet.contracts.enums import IdentityRole

from ._base import ApiSchema


class QrLoginStartRequest(ApiSchema):
    """Body for ``POST /v1/identities/qr-login``.

    Same identity metadata as the file-upload provision form, minus the file —
    the session is minted live by scanning the QR. Telegram api_id/api_hash are
    required up front: they build the client that generates the QR.
    """

    name: str = Field(min_length=1, max_length=128)
    source_id: UUID
    telegram_api_id: int
    telegram_api_hash: str = Field(min_length=1, max_length=256)
    monitor_groups: list[str] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=21_600, ge=0)
    proxy_uri: str | None = Field(default=None, max_length=1024)
    role: IdentityRole = IdentityRole.MONITOR
    notes: str | None = Field(default=None, max_length=4096)


class QrLoginChallenge(ApiSchema):
    """201 response of ``POST /v1/identities/qr-login`` — render ``qr_url`` as a QR."""

    login_id: UUID
    qr_url: str = Field(description="tg://login?token=... — render as a QR code")
    expires_at: datetime
    status: str = Field(description="pending_scan | password_needed | complete | error | expired")


class QrLoginStatusResponse(ApiSchema):
    """Poll/submit response. On ``complete``, ``identity_id`` is set; on ``error``
    / ``expired``, ``detail`` carries a concise reason. ``qr_url`` refreshes as the
    token is regenerated while pending."""

    status: str
    qr_url: str | None = None
    identity_id: UUID | None = None
    detail: str | None = None


class QrPasswordRequest(ApiSchema):
    """Body for ``POST /v1/identities/qr-login/{login_id}/password`` (2FA step)."""

    password: str = Field(min_length=1, max_length=512)


__all__ = [
    "QrLoginChallenge",
    "QrLoginStartRequest",
    "QrLoginStatusResponse",
    "QrPasswordRequest",
]
