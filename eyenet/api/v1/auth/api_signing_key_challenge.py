# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/signing-key/challenge — mint a registration proof-of-possession.

Self-service (PHASE-4): an authenticated operator requests a short-lived,
single-use, user-bound challenge nonce. The operator signs
`EYENET-SIGNING-KEY-CHALLENGE-v1(nonce, public_key)` with the candidate
private key and submits it to `POST /v1/auth/signing-key`. No special scope —
like MFA enroll, the bearer identity IS the authorization.

Rate-limiting the challenge mint is deferred (small-operator scope): the nonce
is single-use with a 60s TTL, and the registration step is the authenticated
boundary that actually mutates state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, get_current_user, get_storage
from eyenet.api.v1.schemas.auth import SigningKeyChallengeResponse
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["auth"])

# Mirrors the storage-layer challenge TTL (``_SIGNING_KEY_CHALLENGE_TTL`` in
# the FileAccessMixin). Reported to the client as the signing deadline; the
# storage UPDATE's ``expires_at > now`` predicate is the authoritative gate.
_CHALLENGE_TTL = timedelta(seconds=60)


@router.post(
    "/auth/signing-key/challenge",
    operation_id="auth_signing_key_challenge",
    response_model=SigningKeyChallengeResponse,
    status_code=200,
)
async def auth_signing_key_challenge(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> SigningKeyChallengeResponse:
    now = datetime.now(tz=UTC)
    nonce = await storage.mint_signing_key_challenge(current_user.user_id, now=now)
    return SigningKeyChallengeResponse(nonce=nonce, expires_at=now + _CHALLENGE_TTL)
