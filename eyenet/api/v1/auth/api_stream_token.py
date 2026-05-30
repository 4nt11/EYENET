# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/stream-token — short-lived token for SSE EventSource (no header auth)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from eyenet.api.auth import STREAM_TTL, load_signing_keypair, mint_stream_token
from eyenet.api.deps import CurrentUser, ScopeForbidden, get_audit, get_current_user
from eyenet.api.v1.schemas.auth import StreamTokenMinted, StreamTokenRequest
from eyenet.api.v1.stream import STREAM_TOPIC_SCOPE
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/stream-token",
    operation_id="auth_mint_stream_token",
    response_model=StreamTokenMinted,
    status_code=200,
)
async def auth_mint_stream_token(
    body: StreamTokenRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> StreamTokenMinted:
    # Live authority gate: each requested topic requires the matching
    # `stream:*` scope in the caller's CURRENT effective scopes. The token then
    # freezes those topics — but it lives ≤15 min, and the SSE delivery path
    # re-resolves authority at connect, so a revoked role still cuts the stream.
    for topic in body.topics:
        scope = STREAM_TOPIC_SCOPE[topic]
        if scope not in current_user.effective_scopes:
            raise ScopeForbidden(scope)

    now = datetime.now(tz=UTC)
    ttl = timedelta(seconds=min(body.ttl_seconds, int(STREAM_TTL.total_seconds())))
    # Mint with the same RS256 keypair as access tokens (reuse, don't fork the
    # key material); `typ:"stream"` isolates it from the normal bearer path.
    signing_key = load_signing_keypair(request.app.state.data_dir)
    token, claims = mint_stream_token(
        user_id=current_user.user_id,
        topics=[topic.value for topic in body.topics],
        ttl=ttl,
        signing_key=signing_key,
        now=now,
    )

    await audit.emit(
        event="eyenet.audit.auth.stream_token.minted",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={
            "jti": str(claims.jti),
            "topics": list(claims.topics),
            "expires_at": claims.expires_at.isoformat(),
            # The token itself is NEVER logged — it is a bearer credential.
        },
    )

    return StreamTokenMinted(
        stream_token=token,
        expires_at=claims.expires_at,
        topics=body.topics,
    )
