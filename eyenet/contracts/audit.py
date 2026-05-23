"""Audit trail — bus envelope + persisted row + hash-chain helpers.

PLAN §9.3 / MODELS §2.14: every `AuditLog` row is hash-chained:
    self_hash = sha256(canonicalized_fields(row, including prev_hash))
Insertion / deletion / edit breaks the chain on a single forward walk.

Audit stream subject template: `eyenet.audit.{service}` (PLAN §3, §9.3).
The wildcard `eyenet.audit.>` is the canonical subscription pattern.

Surface: bus+db.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from ._base import BusEnvelope, DbRowBase

SUBJECT: str = "eyenet.audit.>"


def subject_for(service: str) -> str:
    """Render the audit bus subject for a service name."""

    return f"eyenet.audit.{service}"


# Hash-chain genesis marker. The very first AuditLog row uses this as
# `prev_hash` so a verifier can recognize the chain root.
GENESIS_PREV_HASH: str = "0" * 64


class AuditEvent(BusEnvelope):
    """`eyenet.audit.{service}` bus envelope.

    The persisted twin (`AuditLogRow`) carries the chain hashes; the bus
    envelope does NOT — chain computation happens at write time inside the
    audit store, after the canonical row order is known.
    """

    audit_id: UUID
    event: str = Field(description="dotted, lowercase, stable (e.g. evidence_access)")
    service: str
    instance_id: str
    system_user_id: UUID | None = None
    subject_kind: str = Field(description="e.g. actor, group, message, identity, linkage")
    subject_id: UUID | None = None
    evidence_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    at: datetime


class AuditLogRow(DbRowBase):
    """Persisted, hash-chained audit row (MODELS §2.14)."""

    event: str
    service: str
    instance_id: str
    system_user_id: UUID | None = None
    subject_kind: str
    subject_id: UUID | None = None
    evidence_ref: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    at: datetime
    prev_hash: str = Field(min_length=64, max_length=64)
    self_hash: str = Field(min_length=64, max_length=64)


# -- Hash-chain helpers ------------------------------------------------------


def _canonicalize_for_hash(row: AuditLogRow) -> bytes:
    """Stable byte-serialization of an AuditLogRow excluding `self_hash`.

    `prev_hash` IS included — that's what makes the chain forward-detectable.
    `id` is included — moving a row breaks the chain.
    """

    data = row.model_dump(mode="json", exclude={"self_hash"})
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_self_hash(row: AuditLogRow) -> str:
    """Compute `self_hash` over a canonicalized row (excluding `self_hash`)."""

    return hashlib.sha256(_canonicalize_for_hash(row)).hexdigest()


def verify_chain(rows: list[AuditLogRow]) -> tuple[bool, int | None]:
    """Walk the chain forward.

    Returns `(ok, broken_index)`. `broken_index=None` when the chain is sound;
    otherwise it's the index of the first row whose `prev_hash` or
    `self_hash` failed to verify.
    """

    expected_prev = GENESIS_PREV_HASH
    for idx, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            return False, idx
        if row.self_hash != compute_self_hash(row):
            return False, idx
        expected_prev = row.self_hash
    return True, None


__all__ = [
    "GENESIS_PREV_HASH",
    "SUBJECT",
    "AuditEvent",
    "AuditLogRow",
    "compute_self_hash",
    "subject_for",
    "verify_chain",
]
