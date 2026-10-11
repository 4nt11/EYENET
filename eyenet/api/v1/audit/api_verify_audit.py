# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/audit/verify — hash-chain integrity check (M9.F4).

Default (anchored): validate the latest signed external-witness anchor, then rehash
ONLY the tail since that checkpoint. Sub-second — the signed anchor attests the
prefix, so the whole 3M-row chain is not re-walked on every poll. Tampering after
the last anchor is still caught by the tail rehash; tampering before it would have
to forge an Ed25519-signed anchor (the signing key, not just DB write).

``?full=1`` (admin only): rehash the ENTIRE chain from genesis, streamed in seq
pages so it completes with bounded memory instead of materializing 3M rows. O(n),
so it is gated to the admin role and meant for a deliberate deep audit.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, Query

from eyenet.api.deps import CurrentUser, RequireScope, ScopeForbidden, get_data_dir, get_storage
from eyenet.api.v1.schemas.audit import AuditChainBreak, AuditVerifyResult
from eyenet.contracts.audit import GENESIS_PREV_HASH, AuditLogRow, compute_self_hash, verify_chain
from eyenet.contracts.enums import SystemUserRole
from eyenet.crypto._anchor_signing import (
    build_anchor_canonical,
    load_anchor_key,
    load_or_create_deployment_id,
)
from eyenet.crypto._file_access_signing import verify_signature
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["audit"])

_PAGE = 5000


def _break_for(row: AuditLogRow, expected_prev: str) -> AuditChainBreak:
    """Classify a broken link: tampered row content vs a broken prev->self link."""
    recomputed = compute_self_hash(row)
    if row.self_hash != recomputed:
        return AuditChainBreak(event_id=row.id, expected_hash=recomputed, actual_hash=row.self_hash)
    return AuditChainBreak(event_id=row.id, expected_hash=expected_prev, actual_hash=row.prev_hash)


async def _verify_segment(
    storage: BaseRepository, *, after_seq: int, expected_prev: str
) -> tuple[bool, AuditChainBreak | None, int]:
    """Walk seq>after_seq in pages, verifying the chain from ``expected_prev``.

    Bounded memory (one page at a time), keystepped by seq. Returns
    ``(ok, first_break, rows_checked)``.
    """
    prev = expected_prev
    after = after_seq
    checked = 0
    while True:
        page = await storage.audit_chain_page(after_seq=after, limit=_PAGE)
        if not page:
            return True, None, checked
        rows = [row for _, row in page]
        ok, idx = verify_chain(rows, expected_prev=prev)
        if not ok and idx is not None:
            expected = prev if idx == 0 else rows[idx - 1].self_hash
            return False, _break_for(rows[idx], expected), checked + idx
        checked += len(rows)
        prev = rows[-1].self_hash
        after = page[-1][0]


async def _verify_full(storage: BaseRepository) -> AuditVerifyResult:
    ok, brk, checked = await _verify_segment(storage, after_seq=0, expected_prev=GENESIS_PREV_HASH)
    return AuditVerifyResult(verified=ok, rows_checked=checked, first_break=brk, mode="full")


async def _verify_anchored(storage: BaseRepository, data_dir: Path) -> AuditVerifyResult:
    deployment_id = load_or_create_deployment_id(data_dir)
    anchor = await storage.latest_anchor(deployment_id)
    if anchor is None:
        # No checkpoint yet (fresh deploy, < one anchor tick) — nothing to trust the
        # prefix against, so fall back to a full walk (chain is still small here).
        return await _verify_full(storage)

    # 1. External-witness signature over the canonical anchor (Ed25519).
    signer = load_anchor_key(data_dir)
    pub = Ed25519PublicKey.from_public_bytes(signer.verifying_key_bytes)
    canonical = build_anchor_canonical(
        deployment_id=deployment_id,
        anchor_seq=anchor.anchor_seq,
        anchored_at=anchor.anchored_at.isoformat(),
        audit_head=anchor.audit_head,
        journal_head=anchor.journal_head,
    )
    try:
        raw_sig = base64.urlsafe_b64decode(anchor.signature.split(":", 1)[1])
    except (ValueError, IndexError):
        raw_sig = b""
    sig_ok = verify_signature(pub, canonical, raw_sig)

    # 2. Locate the attested head in the live chain (unique self_hash index). Absent
    #    => the chain was rolled back or forked past the anchor.
    checkpoint_seq = await storage.audit_seq_for_self_hash(anchor.audit_head)
    if checkpoint_seq is None:
        return AuditVerifyResult(
            verified=False,
            rows_checked=0,
            first_break=None,
            mode="anchored",
            anchor_seq=anchor.anchor_seq,
            anchor_signature_ok=sig_ok,
        )

    # 3. Rehash only the tail from the trusted checkpoint head to the tip.
    tail_ok, brk, checked = await _verify_segment(
        storage, after_seq=checkpoint_seq, expected_prev=anchor.audit_head
    )
    return AuditVerifyResult(
        verified=sig_ok and tail_ok,
        rows_checked=checked,
        first_break=brk,
        mode="anchored",
        anchor_seq=anchor.anchor_seq,
        anchor_signature_ok=sig_ok,
    )


@router.get(
    "/audit/verify",
    operation_id="audit_verify",
    response_model=AuditVerifyResult,
    status_code=200,
)
async def audit_verify(
    current_user: Annotated[CurrentUser, Depends(RequireScope("read:audit"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
    data_dir: Annotated[Path, Depends(get_data_dir)],
    full: Annotated[
        bool, Query(description="Rehash the ENTIRE chain from genesis (admin only; O(n)).")
    ] = False,
) -> AuditVerifyResult:
    if full:
        if current_user.role != SystemUserRole.ADMIN:
            # Full re-verification is an expensive admin-only deep audit.
            raise ScopeForbidden("admin")
        return await _verify_full(storage)
    return await _verify_anchored(storage, data_dir)
