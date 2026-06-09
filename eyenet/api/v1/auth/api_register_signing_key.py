# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /v1/auth/signing-key — register an operator verifying key (PHASE-4).

Self-service ONLY: the authenticated operator enrolls THEIR OWN Ed25519 public
key, proving possession of the matching private key by signing the challenge
minted at `POST /v1/auth/signing-key/challenge`. No admin-override path, no
special scope — the bearer identity IS the authorization (like MFA enroll).

Registration ROTATES: recording a key retires any prior active key for the
operator (one-active invariant, B1). The prior key's history row is preserved
so signatures it already produced still verify.

Failure mapping (fail closed — register nothing on any failure):
  * Malformed key/signature material → 422 at the schema boundary (clean, no
    500): base64-decode + Ed25519 length checks live on the request model.
  * Failed proof-of-possession / unusable (replayed, expired, unknown,
    wrong-user) challenge → 401 via :class:`AuthError`. A failed PoP is an
    authentication failure on this boundary; the generic 401 gives no
    enumeration oracle distinguishing the two.
  * Unauthenticated → 401 via the ``get_current_user`` dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import AuthError, CurrentUser, get_audit, get_current_user, get_storage
from eyenet.api.v1.auth._signing_key_registration import (
    SigningKeyRegistrationError,
    register_operator_signing_key,
)
from eyenet.api.v1.schemas.auth import SigningKeyRegisterRequest, SigningKeyRegisterResponse
from eyenet.storage.repository import BaseRepository
from eyenet.telemetry.audit import AuditEmitter

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/signing-key",
    operation_id="auth_register_signing_key",
    response_model=SigningKeyRegisterResponse,
    status_code=200,
)
async def auth_register_signing_key(
    body: SigningKeyRegisterRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    audit: Annotated[AuditEmitter, Depends(get_audit)],
) -> SigningKeyRegisterResponse:
    now = datetime.now(tz=UTC)
    try:
        fingerprint = await register_operator_signing_key(
            storage,
            user_id=current_user.user_id,
            public_key_bytes=body.public_key_bytes,
            challenge_nonce=body.challenge_nonce,
            challenge_signature=body.challenge_signature,
            now=now,
        )
    except SigningKeyRegistrationError as exc:
        await audit.emit(
            event="eyenet.audit.auth.signing_key_registration_failed",
            subject_kind="system_user",
            subject_id=current_user.user_id,
            system_user_id=current_user.user_id,
            payload={"username": current_user.username, "reason": exc.reason},
        )
        # Generic 401 — no oracle distinguishing bad-proof from bad-nonce.
        raise AuthError("signing_key_registration_failed") from exc

    await audit.emit(
        event="eyenet.audit.auth.signing_key_registered",
        subject_kind="system_user",
        subject_id=current_user.user_id,
        system_user_id=current_user.user_id,
        payload={"username": current_user.username, "fingerprint": fingerprint},
    )
    return SigningKeyRegisterResponse(fingerprint=fingerprint, active_at=now)
