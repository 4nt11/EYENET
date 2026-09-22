# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared §4.9 reclassify handler core for observation / attachment / document.

The three surfaces differ only in the subject kind, the storage call, and the
content hash that binds the signature. Everything else - the grant resolution,
the mandatory operator-signature verify, the monotone guard, and the
``reclassify.rejected`` audit on every refusal - is identical, so it lives here.

Rejection mapping (§4.9):
  no active admin:reclassify grant -> 403 (audit: no_active_grant)
  missing / invalid operator signature -> 403 (audit: bad_signature)
  would demote or same-tier no-op    -> 422 (audit: would_demote / no_change)
  subject row absent                 -> 404 (no audit; not a real subject)

The 403 bodies are generic ("missing required scope") so they leak no oracle;
the precise reason is recorded in the tamper-evident audit row, which is the
court-defensible record §4.9 requires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.api.deps import (
    AuthError,
    ResourceNotFound,
    ScopeForbidden,
    UnprocessableError,
)
from eyenet.api.v1._clearance import resolve_scope_grant
from eyenet.api.v1._operator_signature import decode_operator_signature
from eyenet.api.v1.reclassify._reclassify_canonical import (
    build_reclassify_canonical,
    compute_reclassify_body_hash,
)
from eyenet.api.v1.schemas.reclassify import ReclassificationResult
from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import ClearanceScope
from eyenet.crypto import fingerprint, load_ed25519_public_key, verify_signature
from eyenet.storage.errors import ReclassifyDemotionError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from fastapi import Request

    from eyenet.api.deps import CurrentUser
    from eyenet.api.v1.schemas.reclassify import ReclassificationRequest
    from eyenet.contracts.enums import ReclassificationSubjectKind
    from eyenet.storage.reclassify import ReclassifyOutcome
    from eyenet.storage.repository import BaseRepository
    from eyenet.telemetry.audit import AuditEmitter

    ReclassifyCall = Callable[..., Awaitable[ReclassifyOutcome]]


async def _emit_rejected(
    audit: AuditEmitter,
    *,
    subject_kind: ReclassificationSubjectKind,
    subject_id: UUID,
    attempted_tier: str,
    rejection_reason: str,
    user_id: UUID,
    grant_id: UUID | None = None,
) -> None:
    payload: dict[str, object] = {
        "subject_id": str(subject_id),
        "subject_kind": subject_kind.value,
        "attempted_tier": attempted_tier,
        "rejection_reason": rejection_reason,
        "user_id": str(user_id),
    }
    if grant_id is not None:
        payload["grant_id"] = str(grant_id)
    await audit.emit(
        event=AuditSubject.RECLASSIFY_REJECTED.value,
        subject_kind=subject_kind.value,
        subject_id=subject_id,
        system_user_id=user_id,
        payload=payload,
    )


async def perform_reclassify(
    *,
    subject_kind: ReclassificationSubjectKind,
    subject_id: UUID,
    content_hash: str,
    body: ReclassificationRequest,
    request: Request,
    current_user: CurrentUser,
    storage: BaseRepository,
    audit: AuditEmitter,
    do_reclassify: ReclassifyCall,
) -> ReclassificationResult:
    req = body

    # 1. Authority: an active admin:reclassify grant. RequireScope already proved
    #    the scope; this resolves the concrete grant id for the audit trail.
    grant_id = await resolve_scope_grant(current_user, storage, ClearanceScope.ADMIN_RECLASSIFY)
    if grant_id is None:
        await _emit_rejected(
            audit,
            subject_kind=subject_kind,
            subject_id=subject_id,
            attempted_tier=req.new_tier.value,
            rejection_reason="no_active_grant",
            user_id=current_user.user_id,
        )
        raise ScopeForbidden(ClearanceScope.ADMIN_RECLASSIFY.value)

    # 2. Intent: a valid operator Ed25519 signature. A JWT alone never authorises.
    verifying_key_bytes = await storage.active_signing_key_for(current_user.user_id)
    if verifying_key_bytes is None:
        raise AuthError("no_active_signing_key")
    verifying_key = load_ed25519_public_key(verifying_key_bytes)
    if verifying_key is None:
        raise AuthError("active_signing_key_unloadable")
    key_fingerprint = fingerprint(verifying_key)
    signature = decode_operator_signature(req.operator_signature)
    body_hash = compute_reclassify_body_hash(req.model_dump())
    canonical = build_reclassify_canonical(
        url=request.url.path, body_hash=body_hash, content_hash=content_hash
    )
    if not verify_signature(verifying_key, canonical, signature):
        await _emit_rejected(
            audit,
            subject_kind=subject_kind,
            subject_id=subject_id,
            attempted_tier=req.new_tier.value,
            rejection_reason="bad_signature",
            user_id=current_user.user_id,
            grant_id=grant_id,
        )
        raise ScopeForbidden(ClearanceScope.ADMIN_RECLASSIFY.value)

    # 3. Promote. Storage is the monotone authority (CHECK + raise); it self-audits
    #    the success (reclassify.<kind>) and the demotion (reclassify.rejected).
    try:
        outcome = await do_reclassify(
            grant_id=grant_id,
            operator_signature_pubkey_fingerprint=key_fingerprint,
        )
    except ReclassifyDemotionError as exc:
        raise UnprocessableError(str(exc)) from exc
    except ValueError as exc:
        raise ResourceNotFound(f"{subject_kind.value}:{subject_id}") from exc

    if outcome.audit_event_id is None or outcome.operator_tier_override is None:
        # Same-tier no-op: not a demotion, but no promotion happened either.
        await _emit_rejected(
            audit,
            subject_kind=subject_kind,
            subject_id=subject_id,
            attempted_tier=req.new_tier.value,
            rejection_reason="no_change",
            user_id=current_user.user_id,
            grant_id=grant_id,
        )
        raise UnprocessableError(
            f"new_tier {req.new_tier.value} is not higher than the current effective tier"
        )

    return ReclassificationResult(
        subject_id=subject_id,
        subject_kind=subject_kind,
        classifier_tier=outcome.classifier_tier,
        operator_tier_override=outcome.operator_tier_override,
        effective_tier=outcome.effective_tier,
        prior_effective_tier=outcome.prior_effective_tier,
        audit_event_id=outcome.audit_event_id,
        reclassified_at=outcome.reclassified_at,
        grant_id=grant_id,
    )


__all__ = ["perform_reclassify"]
