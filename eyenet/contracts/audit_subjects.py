"""Canonical registry of `eyenet.audit.*` subject strings (PLAN §4.2).

Single source of truth for every audit event subject. Callers MUST import
from here rather than passing free strings. New subjects added during M9.1+
are listed here; M9.1a registers clearance, reclassification, and case
events per API_PLAN §4.8 / §4.9 / §4.10.

Surface: — (interface).
"""

from __future__ import annotations

from enum import StrEnum


class AuditSubject(StrEnum):
    """Every `event` value valid in an `audit_log` row.

    Naming pattern: `eyenet.audit.<domain>.<verb>` — domain groups the
    primitive being acted on, verb is past-tense state transition.
    """

    # --- §4.8 clearance grants ---------------------------------------------
    CLEARANCE_GRANTED = "eyenet.audit.clearance.granted"
    CLEARANCE_REVOKED = "eyenet.audit.clearance.revoked"
    CLEARANCE_EXPIRED = "eyenet.audit.clearance.expired"

    # --- §4.9 reclassification ---------------------------------------------
    RECLASSIFY_OBSERVATION = "eyenet.audit.reclassify.observation"
    RECLASSIFY_ATTACHMENT = "eyenet.audit.reclassify.attachment"
    RECLASSIFY_REJECTED = "eyenet.audit.reclassify.rejected"

    # --- §4.10 cases -------------------------------------------------------
    CASE_CREATED = "eyenet.audit.case.created"
    CASE_UPDATED = "eyenet.audit.case.updated"
    CASE_MEMBER_ADDED = "eyenet.audit.case.member_added"
    CASE_MEMBER_REMOVED = "eyenet.audit.case.member_removed"
    CASE_COLLABORATOR_ADDED = "eyenet.audit.case.collaborator_added"
    CASE_COLLABORATOR_REVOKED = "eyenet.audit.case.collaborator_revoked"
    CASE_CLOSED = "eyenet.audit.case.closed"
    CASE_REOPENED = "eyenet.audit.case.reopened"
    CASE_ARCHIVED = "eyenet.audit.case.archived"
    CASE_TIER_CHANGED = "eyenet.audit.case.tier_changed"
    CASE_ACCESS_DENIED = "eyenet.audit.case.access_denied"


__all__ = ["AuditSubject"]
