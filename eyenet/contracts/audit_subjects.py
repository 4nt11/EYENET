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
    # --- §4.12 discovery-loop seed roots (M9.D4 / Group E) -----------------
    # Mutating Case.seed_root_group_ids changes downstream candidate
    # eligibility (the reachable-root dimension of the §4.12.3 predicate).
    CASE_SEED_ROOTS_CHANGED = "eyenet.audit.case.seed_roots_changed"

    # --- §4.12.4 CollectorSupervisor runtime (M9.E3) -----------------------
    # Supervisor reconciled a collector's observed_state toward desired_state.
    COLLECTOR_RECONCILED = "eyenet.audit.collector.reconciled"
    # Supervisor leased a scout + dispatched a join (candidate approved→joining).
    CANDIDATE_JOINING = "eyenet.audit.candidate.joining"
    # --- §4.12.4 collector join execution (M9.E5) --------------------------
    # Collector confirmed the platform join (candidate joining→joined); the
    # Group row + CollectorGroupMembership(joined_via=candidate) are written.
    CANDIDATE_JOINED = "eyenet.audit.candidate.joined"
    # Platform refused / timed out the join (candidate joining→failed); the
    # error is frozen in the candidate's rejection_reason.
    CANDIDATE_FAILED = "eyenet.audit.candidate.failed"
    # --- §4.12.5 scout graduation (M9.E4) ----------------------------------
    IDENTITY_GRADUATED = "eyenet.audit.identity.graduated"
    IDENTITY_BURNED = "eyenet.audit.identity.burned"

    # --- §M10 document classification --------------------------------------
    # Emitted by the ClassifierService (a later slice); the aggregator builds
    # the payload now (eyenet/classifier/aggregate/_audit.py) so callers and the
    # service reference these canonical subjects, never free strings.
    CLASSIFY_AGGREGATED = "eyenet.audit.classify.aggregated"  # a document settled to a tier
    CLASSIFY_REVIEW_FLAGGED = "eyenet.audit.classify.review_flagged"  # operator_review raised


__all__ = ["AuditSubject"]
