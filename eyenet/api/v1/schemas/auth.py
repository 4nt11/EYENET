"""Auth-surface schemas — login, refresh, logout, me, PATs, stream tokens.

The backing storage tables (`system_user_credential`, `refresh_token`,
`personal_access_token`, `jwt_denylist`) land in M9.1 per API_PLAN §4.1;
until then these schemas declare the wire shape only and `from_domain()`
translators are documented TODOs.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Login*, Refresh*, TokenPair,
AccessToken, UserMe, PAT*, StreamToken*.
API_PLAN §3.1, §4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import ApiSchema
from .enums import StreamTopic, SystemUserRole
from .pagination import CursorPage


class LoginRequest(ApiSchema):
    """Body for `POST /v1/auth/login`."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(ApiSchema):
    """Body for `POST /v1/auth/refresh`."""

    refresh_token: str = Field(min_length=16, max_length=256)


class TokenPair(ApiSchema):
    """200 response from `/v1/auth/login`."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class AccessToken(ApiSchema):
    """200 response from `/v1/auth/refresh` — refresh rotates separately."""

    access_token: str
    access_expires_at: datetime
    token_type: Literal["Bearer"] = "Bearer"


class UserMe(ApiSchema):
    """Projection of MODELS.md §2.17 SystemUser for `/v1/auth/me`.

    TODO(M9.1): `from_domain(SystemUserTable, scopes: list[str])` once the
    `system_user_scope` join is wired. Scopes are resolved at request time
    from the backing table — never from a JWT claim (API_PLAN §4.2).
    """

    user_id: UUID
    username: str = Field(max_length=128)
    role: SystemUserRole
    scopes: list[str] = Field(
        default_factory=list,
        description="Flat scope strings granted to this user at the moment of the request.",
    )


class PATSummary(ApiSchema):
    """Projection of API_PLAN §4.1 personal_access_token (TBD M9.1 storage).

    TODO(M9.1): `from_domain(PersonalAccessTokenTable)` once the table exists.
    """

    token_id: UUID
    name: str = Field(max_length=128)
    prefix: str = Field(
        max_length=32,
        description=(
            "Plaintext PAT prefix (`<22-char-prefix>`) for display. The secret is never returned."
        ),
    )
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class PATMintRequest(ApiSchema):
    """Body for `POST /v1/auth/tokens`."""

    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class PATMinted(ApiSchema):
    """201 response from `POST /v1/auth/tokens` — `secret` is plaintext ONCE.

    TODO(M9.1): `from_domain(PersonalAccessTokenTable, secret: str)` — the
    one-time secret is provided by the mint flow, never re-read from storage.
    """

    token_id: UUID
    name: str = Field(max_length=128)
    prefix: str = Field(max_length=32)
    scopes: list[str] = Field(default_factory=list)
    secret: str = Field(
        description="Full PAT (`eyenet_pat_<prefix>_<secret>`). Shown ONCE. Never re-displayed.",
    )
    created_at: datetime
    expires_at: datetime | None = None


class StreamTokenRequest(ApiSchema):
    """Body for `POST /v1/auth/stream-token` — browser SSE fallback."""

    topics: list[StreamTopic] = Field(min_length=1, max_length=16)
    ttl_seconds: int = Field(default=900, ge=60, le=900)


class StreamTokenMinted(ApiSchema):
    """200 response from `POST /v1/auth/stream-token`."""

    stream_token: str
    expires_at: datetime
    topics: list[StreamTopic]


class CursorPagePATSummary(CursorPage[PATSummary]):
    """200 page response for `GET /v1/auth/tokens`."""


__all__ = [
    "AccessToken",
    "CursorPagePATSummary",
    "LoginRequest",
    "PATMintRequest",
    "PATMinted",
    "PATSummary",
    "RefreshRequest",
    "StreamTokenMinted",
    "StreamTokenRequest",
    "TokenPair",
    "UserMe",
]
