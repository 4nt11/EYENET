# SPDX-License-Identifier: AGPL-3.0-or-later
"""
:class:`BaseRepository` — the flat abstract persistence surface.

Every storage operation EYENET performs is an `@abstractmethod` on this
class. Method names are domain-prefixed (``get_case``, ``append_audit``,
``put_observation``, ``reclassify_attachment``) so the flat namespace is
unambiguous across the 16 domains.

Concrete impls live under :mod:`eyenet.storage.sqlmodel_repo` (generic
SQLModel base) and :mod:`eyenet.storage.sqlite` (SQLite dialect override).
Callers obtain a repository via :func:`eyenet.storage.factory.get_repository`
and operate against this ABC only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from eyenet.contracts.access_artifact import GroupAccessArtifactRow
    from eyenet.contracts.attribution import LinkageRow
    from eyenet.contracts.audit import AuditLogRow
    from eyenet.contracts.auth import (
        JwtDenylistRow,
        PersonalAccessTokenRow,
        RefreshTokenRow,
        SystemUserCredentialRow,
        SystemUserScopeRow,
    )
    from eyenet.contracts.candidate import (
        EligibilityInputs,
        GroupCandidateMentionRow,
        GroupCandidateRow,
    )
    from eyenet.contracts.case import CaseCollaboratorRow, CaseMemberRow, CaseRow
    from eyenet.contracts.clearance import SystemUserClearanceGrantRow
    from eyenet.contracts.collector import CollectorRow
    from eyenet.contracts.document import DocumentRow
    from eyenet.contracts.enums import (
        ArtifactSubjectKind,
        ArtifactValidationState,
        CandidateState,
        CaseRoleOnCase,
        CaseSubjectKind,
        ClearanceScope,
        CollectorDesiredState,
        CollectorObservedState,
        GroupAccessKind,
        GroupKind,
        InfrastructureKind,
        JoinedVia,
        MentionKind,
        SensitivityTier,
        SourceDomainPatternKind,
        SourceKind,
        SystemLogLevel,
        SystemUserRole,
    )
    from eyenet.contracts.feedback import FeedbackPairRow
    from eyenet.contracts.infrastructure import InfrastructureArtifactRow
    from eyenet.contracts.membership import CollectorGroupMembershipRow, MessageObservationRow
    from eyenet.contracts.message import AttachmentRow
    from eyenet.contracts.mfa import MfaChallengeRow
    from eyenet.contracts.source import SourceRow
    from eyenet.contracts.source_domain import SourceDomainRow
    from eyenet.contracts.system_user import SystemUserRow


class BaseRepository(ABC):
    """Flat persistence surface. ~70 abstract methods, all async, all
    domain-prefixed."""

    # =================================================================
    # AUDIT (PLAN §9.3, MODELS §2.14)
    # =================================================================

    @abstractmethod
    async def append_audit(self, row_data: dict[str, Any]) -> AuditLogRow:
        """Compute hash-chain and append one row. `row_data` carries every
        :class:`AuditLogRow` field except ``prev_hash`` / ``self_hash`` —
        those are computed at write time."""

    @abstractmethod
    async def all_audit(self) -> list[AuditLogRow]:
        """Return the full audit chain in rowid (= INSERT-commit) order."""

    @abstractmethod
    async def list_audit(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        user: UUID | None = None,
        subject: str | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Filtered, paginated audit rows newest-first (AuditLogRow). (M9.F4)"""

    @abstractmethod
    async def count_audit(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        user: UUID | None = None,
        subject: str | None = None,
    ) -> int: ...

    # =================================================================
    # SYSLOG (PLAN §9.5)
    # =================================================================

    @abstractmethod
    async def append_syslog(
        self,
        *,
        level: SystemLogLevel,
        service: str,
        instance_id: str,
        event: str,
        message: str,
        trace_id: str | None = None,
        span_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        stack_hash: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a SystemLog row. Allowlist-gated for LIFECYCLE/NOTICE;
        WARN/ERROR always pass. Returns False if off-allowlist."""

    # =================================================================
    # CASES (API_PLAN §4.10)
    # =================================================================

    @abstractmethod
    async def create_case(
        self,
        *,
        title: str,
        description: str | None,
        opened_by_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow: ...

    @abstractmethod
    async def update_case(
        self,
        *,
        case_id: UUID,
        title: str | None = None,
        description: str | None = None,
        editor_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow: ...

    @abstractmethod
    async def close_case(
        self,
        *,
        case_id: UUID,
        closer_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow: ...

    @abstractmethod
    async def reopen_case(
        self,
        *,
        case_id: UUID,
        reopener_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow: ...

    @abstractmethod
    async def archive_case(
        self,
        *,
        case_id: UUID,
        archiver_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseRow: ...

    @abstractmethod
    async def get_case(self, case_id: UUID) -> CaseRow | None: ...

    @abstractmethod
    async def list_case_members(self, case_id: UUID) -> list[CaseMemberRow]: ...

    @abstractmethod
    async def list_case_collaborators(
        self,
        case_id: UUID,
    ) -> list[CaseCollaboratorRow]: ...

    @abstractmethod
    async def add_case_member(
        self,
        *,
        case_id: UUID,
        subject_kind: CaseSubjectKind,
        subject_id: UUID,
        added_by_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseMemberRow: ...

    @abstractmethod
    async def remove_case_member(
        self,
        *,
        member_id: UUID,
        remover_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseMemberRow: ...

    @abstractmethod
    async def add_case_collaborator(
        self,
        *,
        case_id: UUID,
        user_id: UUID,
        role: CaseRoleOnCase,
        granted_by_user_id: UUID,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseCollaboratorRow: ...

    @abstractmethod
    async def revoke_case_collaborator(
        self,
        *,
        collaborator_id: UUID,
        revoker_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> CaseCollaboratorRow: ...

    @abstractmethod
    async def emit_case_access_denied(
        self,
        *,
        case_id: UUID,
        user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None: ...

    # =================================================================
    # CLEARANCE (API_PLAN §4.8)
    # =================================================================

    @abstractmethod
    async def grant_clearance(
        self,
        *,
        grantee_user_id: UUID,
        granter_user_id: UUID,
        scope: ClearanceScope,
        reason: str,
        expires_at: datetime,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> SystemUserClearanceGrantRow: ...

    @abstractmethod
    async def revoke_clearance(
        self,
        *,
        grant_id: UUID,
        revoker_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> SystemUserClearanceGrantRow: ...

    @abstractmethod
    async def expire_due_clearances(
        self,
        *,
        now: datetime | None = None,
        service: str,
        instance_id: str,
    ) -> list[UUID]: ...

    @abstractmethod
    async def active_clearance_grants_for(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> list[SystemUserClearanceGrantRow]:
        """Cache-bypass critical path (API_PLAN §4.4.1)."""

    @abstractmethod
    async def effective_clearance_scopes(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> frozenset[ClearanceScope]: ...

    # =================================================================
    # OBSERVATIONS (MODELS §2.3, API_PLAN §4.9)
    # =================================================================

    @abstractmethod
    async def put_observations_bulk(self, observation_rows: list[object]) -> None:
        """Persist many observation rows in one session."""

    @abstractmethod
    async def put_observation(self, observation_row: object) -> None:
        """Persist an :class:`ObservationRow`. Type-erased to avoid
        contract-layer coupling at the ABC."""

    @abstractmethod
    async def latest_observations(
        self,
        actor_id: UUID,
        primitive_name: str,
        limit: int = 1,
    ) -> list[object]: ...

    @abstractmethod
    async def observation_by_evidence_and_primitive(
        self,
        evidence_ref: str,
        primitive_name: str,
    ) -> object | None: ...

    @abstractmethod
    async def observations_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Observations for an actor, newest-first, with optional time window.
        Returns ObservationTable rows (type-erased). (M9.F1)"""

    @abstractmethod
    async def count_observations_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int: ...

    @abstractmethod
    async def count_observations(self) -> int: ...

    @abstractmethod
    async def reclassify_observation(
        self,
        *,
        observation_id: UUID,
        new_tier: SensitivityTier,
        operator_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> object:
        """Monotone-up only; demotion raises
        :class:`ReclassifyDemotionError` and emits
        ``reclassify.rejected``."""

    # =================================================================
    # ATTACHMENTS (MODELS §2.9, API_PLAN §4.9)
    # =================================================================

    @abstractmethod
    async def put_attachment(self, attachment_row: object) -> UUID: ...

    @abstractmethod
    async def get_attachment(self, attachment_id: UUID) -> AttachmentRow | None: ...

    @abstractmethod
    async def set_attachment_classification(
        self,
        attachment_id: UUID,
        tier: SensitivityTier,
    ) -> None:
        """Stamp the classifier-AUTHORITATIVE ``classifier_tier`` (M10 slice 8).

        Distinct from :meth:`reclassify_attachment` (the operator-promote path,
        which writes ``operator_tier_override`` monotone-up). This is the
        classifier setting its own verdict and is idempotent on replay."""

    @abstractmethod
    async def reclassify_attachment(
        self,
        *,
        attachment_id: UUID,
        new_tier: SensitivityTier,
        operator_user_id: UUID,
        reason: str,
        now: datetime | None = None,
        service: str,
        instance_id: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> object: ...

    # =================================================================
    # DOCUMENTS (MODELS §2.10, M10 classifier)
    # =================================================================

    @abstractmethod
    async def put_document(self, document_row: object) -> UUID: ...

    @abstractmethod
    async def get_document(self, document_id: UUID) -> DocumentRow | None: ...

    @abstractmethod
    async def settle_document_classification(
        self,
        document_id: UUID,
        *,
        tier: SensitivityTier,
        extracted_text: str | None,
        embedded_meta: dict[str, Any],
        classification: dict[str, Any],
        review_required: bool,
        ingested_at: datetime,
    ) -> None:
        """Settle a provisional CLASSIFIED upload to its computed tier (slice 8).

        Overwrites the staged row's classification fields once the async
        pipeline finishes. Idempotent on replay (deterministic verdict)."""

    # =================================================================
    # MESSAGES (PLAN §4.3, MODELS §1.4)
    # =================================================================

    @abstractmethod
    async def get_message_body(self, evidence_ref: str) -> bytes | None: ...

    @abstractmethod
    async def get_message_id_by_evidence_ref(
        self,
        evidence_ref: str,
    ) -> UUID | None: ...

    @abstractmethod
    async def put_message(
        self,
        row: object,
        attachments: Any = None,
    ) -> bool:
        """Persist MessageTable + AttachmentTable rows in one transaction.
        Returns True on insert, False if `evidence_ref` already exists."""

    @abstractmethod
    async def recent_message_bodies_for_actor(
        self,
        actor_id: UUID,
        *,
        limit: int,
    ) -> list[str]:
        """Return up to ``limit`` recent non-empty bodies for an actor,
        oldest-first. Used by the Verifier window-corpus loader."""

    @abstractmethod
    async def messages_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Messages sent by an actor, newest-first, with optional time window.
        Returns MessageTable rows (type-erased) for the timeline. (M9.F1)"""

    @abstractmethod
    async def count_messages_for_actor(
        self,
        actor_id: UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int: ...

    @abstractmethod
    async def resolve_message_id(
        self,
        *,
        source_id: UUID,
        group_id: UUID,
        platform_msgid: str,
    ) -> UUID | None:
        """Bridge platform msg-id to internal MessageTable.id.

        Replies, edits, reactions all reference target messages by
        platform id (Matrix event_id, Telegram msg_id). Returns None
        when the target hasn't been ingested yet — caller decides
        whether to drop, stash, or defer (see
        :mod:`reply_resolver`-style M9 deferred backfill).
        """

    # =================================================================
    # CORPUS (MODELS §2.6)
    # =================================================================

    @abstractmethod
    async def append_corpus(
        self,
        actor_id: UUID,
        ts: datetime,
        evidence_ref: str,
        message_length: int,
        language: str | None,
    ) -> None: ...

    @abstractmethod
    async def iter_corpus_since(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str]]: ...

    @abstractmethod
    async def iter_corpus_since_with_reply(
        self,
        actor_id: UUID,
        since_ts: datetime,
        since_msg_id: UUID,
    ) -> list[tuple[datetime, UUID, str, UUID | None]]: ...

    # =================================================================
    # CURSORS (MODELS §2.16)
    # =================================================================

    @abstractmethod
    async def get_cursors_bulk(
        self,
        actor_id: UUID,
        primitive_names: Any,
    ) -> dict[str, Any]:
        """Bulk-read cursors for several primitives in one round-trip."""

    @abstractmethod
    async def get_cursor(
        self,
        actor_id: UUID,
        primitive_name: str,
    ) -> tuple[datetime, UUID]:
        """Return `(last_processed_msg_ts, last_processed_msg_id)` or
        the epoch/nil-UUID sentinel pair."""

    @abstractmethod
    async def set_cursors_bulk(
        self,
        actor_id: UUID,
        updates: Any,
    ) -> None:
        """Apply many cursor updates in one session."""

    @abstractmethod
    async def set_cursor(
        self,
        actor_id: UUID,
        primitive_name: str,
        last_ts: datetime,
        last_msg_id: UUID,
    ) -> None: ...

    # =================================================================
    # PROFILES (MODELS §2.4)
    # =================================================================

    @abstractmethod
    async def get_current_profile(self, actor_id: UUID) -> object | None: ...

    @abstractmethod
    async def upsert_current_profile(self, profile_row: object) -> None: ...

    @abstractmethod
    async def profile_history(self, actor_id: UUID) -> list[object]: ...

    # =================================================================
    # VECTORS (similarity search)
    # =================================================================

    @abstractmethod
    async def upsert_simhash(
        self,
        actor_id: UUID,
        primitive_name: str,
        simhash_hex: str,
    ) -> None: ...

    @abstractmethod
    async def nearest_simhashes(
        self,
        primitive_name: str,
        simhash_hex: str,
        max_distance: int,
        limit: int = 50,
        exclude_actor_id: UUID | None = None,
    ) -> list[Any]:
        """Return list[VectorMatch] sorted by Hamming distance ascending."""

    # =================================================================
    # GRAPH (MODELS §2.11)
    # =================================================================

    @abstractmethod
    async def upsert_graph_node(
        self,
        node_type: str,
        node_id: UUID,
        attrs: dict[str, object],
    ) -> None: ...

    @abstractmethod
    async def upsert_graph_edge(
        self,
        edge_type: str,
        src_id: UUID,
        dst_id: UUID,
        attrs: dict[str, object],
    ) -> None: ...

    @abstractmethod
    async def delete_graph_edge(
        self,
        edge_type: str,
        src_id: UUID,
        dst_id: UUID,
    ) -> None: ...

    @abstractmethod
    async def graph_neighbors(
        self,
        node_id: UUID,
        edge_type: str | None = None,
    ) -> list[tuple[UUID, str, dict[str, object]]]: ...

    @abstractmethod
    async def graph_neighbor_edges(
        self,
        node_id: UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Outbound edges from a node as GraphEdgeTable rows (type-erased),
        for the typed-edge neighbor projector. (M9.F1)"""

    @abstractmethod
    async def count_graph_neighbors(self, node_id: UUID) -> int: ...

    @abstractmethod
    async def graph_edges_by_type(
        self,
        edge_type: str,
        src_id: UUID | None = None,
        dst_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, dict[str, object]]]: ...

    @abstractmethod
    async def graph_stats(self) -> dict[str, int]: ...

    # =================================================================
    # LINKAGES (MODELS §2.5)
    # =================================================================

    @abstractmethod
    async def insert_proposed_linkage(
        self,
        actor_a: UUID,
        actor_b: UUID,
        method: str,
        score: float,
        evidence: dict[str, Any],
        *,
        linkage_id: UUID | None = None,
    ) -> LinkageRow: ...

    @abstractmethod
    async def transition_linkage(
        self,
        linkage_id: UUID,
        new_state: object,
        decided_by: str,
        notes: str | None = None,
    ) -> object: ...

    @abstractmethod
    async def get_linkage(self, linkage_id: UUID) -> LinkageRow | None: ...

    @abstractmethod
    async def list_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        limit: int = 100,
        offset: int = 0,
        *,
        method: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[object]: ...

    @abstractmethod
    async def count_linkages(
        self,
        actor_id: UUID | None = None,
        state: object | None = None,
        *,
        method: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int: ...

    @abstractmethod
    async def confirmed_linkage_pairs(self) -> list[tuple[UUID, UUID]]: ...

    # =================================================================
    # PERSONAS (MODELS §2.10)
    # =================================================================

    @abstractmethod
    async def persona_for_actor(self, actor_id: UUID) -> object | None: ...

    @abstractmethod
    async def merge_actors_into_persona(
        self,
        actor_a: UUID,
        actor_b: UUID,
        via_linkage_id: UUID,
    ) -> object: ...

    @abstractmethod
    async def split_actor_from_persona(
        self,
        actor_id: UUID,
    ) -> object | None: ...

    @abstractmethod
    async def get_persona(self, persona_id: UUID) -> object | None: ...

    @abstractmethod
    async def persona_members(self, persona_id: UUID) -> list[UUID]: ...

    @abstractmethod
    async def list_persona_memberships(
        self,
        persona_id: UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[object]:
        """Membership rows for a persona, oldest-join-first (type-erased
        PersonaMembershipTable rows) for the members projector. (M9.F1)"""

    @abstractmethod
    async def count_persona_memberships(self, persona_id: UUID) -> int: ...

    @abstractmethod
    async def count_personas(self) -> int: ...

    @abstractmethod
    async def all_personas(self) -> list[object]: ...

    # =================================================================
    # FEEDBACK (M8 verifier)
    # =================================================================

    @abstractmethod
    async def record_feedback_pair(
        self,
        *,
        linkage_id: UUID,
        actor_a: UUID,
        actor_b: UUID,
        ground_truth: str,
        decided_by: str,
        decided_at: datetime,
        notes: str | None = None,
    ) -> FeedbackPairRow: ...

    @abstractmethod
    async def get_feedback_pair(
        self,
        linkage_id: UUID,
    ) -> FeedbackPairRow | None: ...

    @abstractmethod
    async def all_feedback_pairs(self) -> list[tuple[UUID, UUID, str]]: ...

    # =================================================================
    # ACTORS / SOURCES / GROUPS (ingest helpers, MODELS §1.x)
    # =================================================================

    @abstractmethod
    async def upsert_source(
        self,
        *,
        kind: SourceKind,
        display_name: str,
        created_at: datetime,
    ) -> UUID:
        """Upsert a :class:`SourceTable` row by ``(kind, display_name)``.

        ``canonical_url`` is never set here — it's operator-bound via
        :meth:`set_source_canonical_url` after a primary
        :class:`SourceDomainTable` row exists. Collectors call this on
        startup to ensure their Source exists; the operator wires the
        display URL later.
        """

    @abstractmethod
    async def upsert_group(
        self,
        *,
        source_id: UUID,
        platform_groupid: str,
        kind: GroupKind,
        title: str | None,
        seen_at: datetime,
    ) -> UUID: ...

    @abstractmethod
    async def upsert_actor(
        self,
        *,
        source_id: UUID,
        actor_key: str,
        platform_userid: str,
        handle: str | None,
        display_name: str | None,
        seen_at: datetime,
    ) -> UUID: ...

    @abstractmethod
    async def resolve_actor_id(self, actor_key: str) -> UUID | None: ...

    @abstractmethod
    async def get_actor(self, actor_id: UUID) -> object | None:
        """Return the ActorRow for a primary-key id, or None (M9.F1)."""

    @abstractmethod
    async def get_source(self, source_id: UUID) -> object | None:
        """Return the SourceRow for a primary-key id, or None (M9.F1)."""

    @abstractmethod
    async def count_actors(self) -> int: ...

    @abstractmethod
    async def search_actors(self, q: str, *, limit: int, offset: int = 0) -> list[object]:
        """Actors whose handle/display name contain ``q`` (ANSI substring),
        newest-activity first; ActorTable rows type-erased. (M9.F3)"""

    @abstractmethod
    async def count_search_actors(self, q: str) -> int: ...

    # =================================================================
    # SOURCE DOMAINS (MODELS §2.26, API_PLAN §4.13)
    # =================================================================

    @abstractmethod
    async def add_source_domain(
        self,
        *,
        source_id: UUID,
        pattern: str,
        pattern_kind: SourceDomainPatternKind,
        is_primary: bool,
        created_at: datetime,
        created_by_user_id: UUID | None = None,
        notes: str | None = None,
    ) -> SourceDomainRow:
        """Normalize pattern, detect overlap in-transaction, insert.

        Raises :exc:`eyenet.storage.errors.SourceDomainOverlapError` if the
        candidate ``(pattern, pattern_kind)`` can match any hostname also
        matched by an existing non-removed SourceDomain row (global across
        all Sources — no ambiguous routing).

        Raises :class:`ValueError` if ``pattern`` is not a valid hostname
        (delegates to :func:`eyenet.util.domain.normalize_host`).
        """

    @abstractmethod
    async def remove_source_domain(
        self,
        *,
        domain_id: UUID,
        removed_at: datetime,
        removed_by_user_id: UUID,
    ) -> SourceDomainRow:
        """Soft-delete: set ``removed_at`` + ``removed_by_user_id``.

        Row remains for audit. Re-adding the same pattern post-removal is
        allowed (it's a new claim, fresh ``id``, fresh ``created_at``).
        """

    @abstractmethod
    async def set_source_canonical_url(
        self,
        *,
        source_id: UUID,
        canonical_url: str | None,
    ) -> SourceRow:
        """Set or clear ``Source.canonical_url`` with primary-domain validation.

        When ``canonical_url`` is not None, the URL's host (normalized via
        :func:`eyenet.util.domain.normalize_host`) must fall under the
        source's active primary :class:`SourceDomainRow`. Raises
        :exc:`eyenet.storage.errors.SourceCanonicalUrlError` otherwise
        with a stable ``reason`` tag (``invalid_url`` /
        ``no_primary_domain`` / ``host_not_owned``).

        Passing ``canonical_url=None`` always clears the field.
        """

    @abstractmethod
    async def find_source_for_host(self, host: str) -> SourceDomainRow | None:
        """Return the SourceDomain row owning ``host``, or ``None``.

        ``host`` is normalized via :func:`eyenet.util.domain.normalize_host`
        before lookup. Specificity order: ``exact`` > ``subdomain_wildcard``
        > ``suffix_match``. Ties within a kind broken by ``created_at ASC``
        (oldest claim wins).
        """

    # =================================================================
    # COLLECTORS (MODELS §2.19, API_PLAN §4.11)
    # =================================================================

    @abstractmethod
    async def create_collector(
        self,
        *,
        instance_name: str,
        kind: SourceKind,
        source_id: UUID,
        identity_id: UUID,
        config: dict[str, Any],
        created_at: datetime,
        created_by_user_id: UUID,
        notes: str | None = None,
    ) -> CollectorRow:
        """Insert a new :class:`CollectorRow`.

        Fresh rows start with ``desired_state=STOPPED`` and
        ``observed_state=STOPPED``. The operator transitions the
        ``desired_state`` after creation (M9.D2's ``POST .../start``).

        Raises :class:`IntegrityError` if ``identity_id`` is already
        bound to another collector (one-to-one is enforced by the
        column-level unique constraint per API_PLAN §4.11.3) or
        ``instance_name`` collides.
        """

    @abstractmethod
    async def get_collector(self, collector_id: UUID) -> CollectorRow | None:
        """Return one collector row by id, or ``None``."""

    @abstractmethod
    async def list_collectors(self) -> list[CollectorRow]:
        """Return every collector row. Order: ``created_at ASC``."""

    @abstractmethod
    async def set_collector_desired_state(
        self,
        *,
        collector_id: UUID,
        desired_state: CollectorDesiredState,
    ) -> CollectorRow:
        """Mutate ``desired_state`` (operator-initiated, API_PLAN §4.11.2).

        ``observed_state`` is never written by this call — the supervisor
        owns that column. Raises :class:`ValueError` if the collector
        doesn't exist.
        """

    @abstractmethod
    async def record_collector_observed_state(
        self,
        *,
        collector_id: UUID,
        observed_state: CollectorObservedState,
        last_heartbeat_at: datetime | None = None,
        last_error_type: str | None = None,
        last_error_message: str | None = None,
        restart_count: int | None = None,
    ) -> CollectorRow:
        """Supervisor-only write of ``observed_state`` and ancillary fields.

        Fields left as ``None`` are NOT cleared — pass an explicit value
        to overwrite. The exception is the ``last_error_*`` pair, which
        is always written as a pair (both ``None`` clears, both set
        records). Raises :class:`ValueError` if the collector doesn't
        exist.
        """

    @abstractmethod
    async def delete_collector(self, collector_id: UUID) -> None:
        """Hard delete (API_PLAN §4.11 — ``DELETE`` row).

        The API layer (M9.D2) gates this on
        ``observed_state == stopped``; the storage layer just executes.
        Raises :class:`ValueError` if the collector doesn't exist.
        """

    # =================================================================
    # CANDIDATES (MODELS §2.20-2.21, API_PLAN §4.12, M9.C4)
    # =================================================================

    @abstractmethod
    async def record_candidate_mention(
        self,
        *,
        source_id: UUID,
        platform_groupid: str,
        observed_by_collector_id: UUID,
        observed_in_group_id: UUID,
        seed_root_id: UUID | None,
        depth_from_root: int,
        mention_evidence_ref: str,
        mention_kind: MentionKind,
        mentioned_at_source: datetime,
        mentioned_at_ingest: datetime,
        mentioning_actor_id: UUID,
        mentioning_actor_role_signal: str | None = None,
        kind_hint: GroupKind | None = None,
        display_name_hint: str | None = None,
    ) -> tuple[GroupCandidateRow, GroupCandidateMentionRow]:
        """Upsert a GroupCandidate by ``(source_id, platform_groupid)`` and
        append a mention provenance row.

        The mention is idempotent: a second call with the same
        ``(source_id + platform_groupid, mention_evidence_ref)`` returns the
        existing rows without inserting a duplicate.
        """

    @abstractmethod
    async def get_candidate(self, candidate_id: UUID) -> GroupCandidateRow | None:
        """Return one GroupCandidateRow by id, or ``None``."""

    @abstractmethod
    async def list_queued_candidates(
        self,
        *,
        source_id: UUID | None = None,
    ) -> list[GroupCandidateRow]:
        """Return QUEUED candidates ordered by score DESC.

        Pass ``source_id`` to restrict to one Source; omit for all Sources.
        """

    @abstractmethod
    async def transition_candidate(
        self,
        *,
        candidate_id: UUID,
        to_state: CandidateState,
        reviewed_by: str | None = None,
        reviewed_at: datetime | None = None,
        rejection_reason: str | None = None,
        assigned_collector_id: UUID | None = None,
        resulting_group_id: UUID | None = None,
    ) -> GroupCandidateRow:
        """Apply a legal state transition to a GroupCandidate.

        Raises :class:`ValueError` on an illegal transition or if the
        candidate doesn't exist.
        """

    @abstractmethod
    async def compute_eligibility_inputs(
        self,
        candidate_id: UUID,
    ) -> EligibilityInputs:
        """Return pre-computed eligibility inputs for ``candidate_id``.

        Raises :class:`ValueError` if the candidate doesn't exist.
        """

    # =================================================================
    # MEMBERSHIPS (MODELS §2.22-2.23, M9.C5)
    # =================================================================

    @abstractmethod
    async def open_membership(
        self,
        *,
        collector_id: UUID,
        group_id: UUID,
        joined_at: datetime,
        joined_via: JoinedVia,
        joined_via_candidate_id: UUID | None = None,
    ) -> CollectorGroupMembershipRow:
        """Record that a collector joined a group.

        Raises :class:`ValueError` if the collector already has an active
        (``left_at IS NULL``) membership for this group.
        """

    @abstractmethod
    async def close_membership(
        self,
        *,
        collector_id: UUID,
        group_id: UUID,
        left_at: datetime,
        left_reason: str,
    ) -> CollectorGroupMembershipRow:
        """Mark a membership as departed (set ``left_at`` + ``left_reason``).

        Raises :class:`ValueError` if no active membership exists.
        """

    @abstractmethod
    async def list_active_memberships(
        self,
        *,
        collector_id: UUID | None = None,
        group_id: UUID | None = None,
    ) -> list[CollectorGroupMembershipRow]:
        """Return active memberships (``left_at IS NULL``).

        Filter by ``collector_id`` to answer "what is this collector in?",
        by ``group_id`` to answer "who is currently in this group?", or omit
        both for all active memberships.
        """

    @abstractmethod
    async def record_observation(
        self,
        *,
        message_id: UUID,
        collector_id: UUID,
        observed_at_ingest: datetime,
    ) -> MessageObservationRow:
        """Record that a collector observed a message; set ``was_first_sighting``.

        ``was_first_sighting`` is True iff this is the first call for this
        ``message_id``. Idempotent on ``(message_id, collector_id)``.
        """

    # =================================================================
    # ARTIFACTS (MODELS §2.7, §2.24, §2.25 bridge resolution, M9.C6)
    # =================================================================

    @abstractmethod
    async def put_infrastructure_artifact(
        self,
        *,
        kind: InfrastructureKind,
        value: str,
        first_seen_at_ingest: datetime,
        last_seen_at_ingest: datetime,
    ) -> InfrastructureArtifactRow:
        """Upsert an InfrastructureArtifact and run §2.25 Path A inline.

        Resolution against existing SourceDomain rows runs in the same
        transaction; ``resolution_state`` + ``resolved_to_source_id`` are
        set before COMMIT. Idempotent on ``value_hash``.
        """

    @abstractmethod
    async def get_infrastructure_artifact(
        self,
        artifact_id: UUID,
    ) -> InfrastructureArtifactRow | None:
        """Return one InfrastructureArtifactRow by id, or ``None``."""

    @abstractmethod
    async def list_artifacts_for_source(
        self,
        source_id: UUID,
    ) -> list[InfrastructureArtifactRow]:
        """Return InfrastructureArtifacts resolved to ``source_id``."""

    @abstractmethod
    async def add_group_access_artifact(
        self,
        *,
        subject_kind: ArtifactSubjectKind,
        group_id: UUID | None,
        candidate_id: UUID | None,
        kind: GroupAccessKind,
        value: str | None,
        discovered_at_ingest: datetime,
        details: dict[str, Any] | None = None,
        discovered_via_mention_id: UUID | None = None,
        validation_state: ArtifactValidationState | None = None,
        requires_admin_approval: bool = False,
        expires_at: datetime | None = None,
    ) -> GroupAccessArtifactRow:
        """Insert a GroupAccessArtifact (MODELS §2.24).

        Exactly one of (group_id, candidate_id) must be populated; the CHECK
        constraint at the SQL layer is the durable backstop.

        ``validation_state`` defaults to ``UNVERIFIED`` when ``None``.
        """

    # =================================================================
    # AUTH (API_PLAN §4.1-§4.6, M9.A1)
    # =================================================================

    @abstractmethod
    async def put_credential(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        password_updated_at: datetime,
        mfa_secret_encrypted: str | None = None,
    ) -> SystemUserCredentialRow:
        """Upsert one credential row keyed by ``user_id`` (one-to-one with user).

        A1 stores opaque hash strings; argon2id format enforcement happens
        at the A2 service layer.
        """

    @abstractmethod
    async def get_credential(self, user_id: UUID) -> SystemUserCredentialRow | None:
        """Return one credential row by user_id, or ``None``."""

    @abstractmethod
    async def delete_credential(self, user_id: UUID) -> None:
        """Delete a credential row. Raises :class:`ValueError` if not found."""

    @abstractmethod
    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        hash_value: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRow:
        """Mint a new refresh token. ``hash_value`` is sha256(opaque secret)."""

    @abstractmethod
    async def get_refresh_token(self, token_id: UUID) -> RefreshTokenRow | None:
        """Return one refresh token by id, or ``None``."""

    @abstractmethod
    async def get_refresh_token_by_hash(
        self,
        hash_value: str,
    ) -> RefreshTokenRow | None:
        """Lookup a refresh token by its sha256 hash, or ``None``."""

    @abstractmethod
    async def revoke_refresh_token(
        self,
        *,
        token_id: UUID,
        revoked_at: datetime,
        replaced_by: UUID | None = None,
    ) -> RefreshTokenRow:
        """Mark a refresh token revoked.

        ``replaced_by`` is the next link in the rotation chain (set on
        /refresh). Omit for logout-style revocation. The CHECK constraint
        rejects ``replaced_by`` without a non-NULL ``revoked_at``.

        Raises :class:`ValueError` if the token doesn't exist.
        """

    @abstractmethod
    async def deny_jwt(
        self,
        *,
        jti: UUID,
        user_id: UUID,
        denied_at: datetime,
        expires_at: datetime,
    ) -> JwtDenylistRow:
        """Insert a JWT denylist entry. Idempotent on ``jti``."""

    @abstractmethod
    async def is_jwt_denylisted(self, jti: UUID) -> bool:
        """Per-request denylist check. Hot path; indexed PK lookup."""

    @abstractmethod
    async def grant_scope(
        self,
        *,
        user_id: UUID,
        scope: str,
        granted_at: datetime,
        granted_by_user_id: UUID,
    ) -> SystemUserScopeRow:
        """Grant an explicit scope to a user (additive to ``ROLE_BASELINE``).

        Idempotent on ``(user_id, scope)`` — re-grant returns the existing row.
        """

    @abstractmethod
    async def revoke_scope(self, *, user_id: UUID, scope: str) -> None:
        """Revoke an explicit scope grant. Raises :class:`ValueError` if no row."""

    @abstractmethod
    async def list_explicit_scopes(
        self,
        user_id: UUID,
    ) -> list[SystemUserScopeRow]:
        """Return all explicit scope grants for a user, ordered by ``granted_at``."""

    # =================================================================
    # MFA (API_PLAN §M9.A3 — TOTP login challenge)
    # =================================================================

    @abstractmethod
    async def create_mfa_challenge(
        self,
        *,
        user_id: UUID,
        issued_at: datetime,
        expires_at: datetime,
    ) -> MfaChallengeRow:
        """Issue a fresh one-shot TOTP login challenge."""

    @abstractmethod
    async def get_mfa_challenge(self, challenge_id: UUID) -> MfaChallengeRow | None:
        """Return one challenge row by id, or ``None``."""

    @abstractmethod
    async def consume_mfa_challenge(
        self,
        *,
        challenge_id: UUID,
        consumed_at: datetime,
    ) -> MfaChallengeRow:
        """Mark a challenge consumed (login/verify success).

        Raises :class:`ValueError` if the challenge doesn't exist OR if it
        has already been consumed (callers treat the second case as replay).
        """

    @abstractmethod
    async def bump_mfa_challenge_failures(self, challenge_id: UUID) -> int:
        """Atomically increment ``failed_attempts`` for a challenge. Returns
        the new count. Raises :class:`ValueError` if the challenge is unknown."""

    @abstractmethod
    async def count_recent_mfa_failures(
        self,
        *,
        user_id: UUID,
        since: datetime,
    ) -> int:
        """Number of challenge rows for ``user_id`` with ``failed_attempts > 0``
        AND ``issued_at >= since``. Drives the 5-fail / 15-min lockout window."""

    @abstractmethod
    async def clear_mfa_failures(
        self,
        *,
        user_id: UUID,
        since: datetime,
    ) -> int:
        """Zero ``failed_attempts`` on all of ``user_id``'s rows with
        ``issued_at >= since``. Returns rows touched. Backs the operator
        unlock path (``eyenet user unlock-mfa``)."""

    # =================================================================
    # Personal Access Tokens (API_PLAN §4.3 — M9.A4)
    # =================================================================

    @abstractmethod
    async def create_personal_access_token(
        self,
        *,
        user_id: UUID,
        name: str,
        prefix: str,
        hash_value: str,
        scopes: list[str],
        created_at: datetime,
        expires_at: datetime | None = None,
    ) -> PersonalAccessTokenRow:
        """Mint a PAT row. ``hash_value`` is HMAC-SHA256(pepper, secret) hex;
        ``scopes`` are frozen at mint. The plaintext secret never reaches storage."""

    @abstractmethod
    async def get_personal_access_token(
        self,
        token_id: UUID,
    ) -> PersonalAccessTokenRow | None:
        """Return one PAT row by id, or ``None``."""

    @abstractmethod
    async def get_personal_access_token_by_hash(
        self,
        hash_value: str,
    ) -> PersonalAccessTokenRow | None:
        """Auth-time lookup by HMAC hex digest. Hot path; UNIQUE-indexed seek."""

    @abstractmethod
    async def list_personal_access_tokens(
        self,
        *,
        user_id: UUID,
        limit: int,
        offset: int = 0,
    ) -> list[PersonalAccessTokenRow]:
        """Return a page of ``user_id``'s PATs, ordered ``created_at`` then
        ``token_id`` descending (newest first). ``limit``/``offset`` drive the
        opaque-cursor pagination at the handler layer."""

    @abstractmethod
    async def count_personal_access_tokens(self, *, user_id: UUID) -> int:
        """Total PAT rows for ``user_id`` (drives ``?include_total``)."""

    @abstractmethod
    async def revoke_personal_access_token(
        self,
        *,
        token_id: UUID,
        revoked_at: datetime,
    ) -> PersonalAccessTokenRow:
        """Mark a PAT revoked. Idempotent — re-revoking keeps the first
        ``revoked_at``. Raises :class:`ValueError` if the token doesn't exist."""

    @abstractmethod
    async def touch_pat_last_used(
        self,
        *,
        token_id: UUID,
        now: datetime,
    ) -> None:
        """Best-effort ``last_used_at`` bump, coarsened to ~60s so a high-rate
        scrape loop isn't a write per request. No-op when already fresh or when
        the token has been revoked."""

    # =================================================================
    # SYSTEM USERS (MODELS §2.17 — operator accounts)
    # =================================================================

    @abstractmethod
    async def put_system_user(
        self,
        *,
        user_id: UUID,
        username: str,
        display_name: str,
        role: SystemUserRole,
        created_at: datetime,
        email: str | None = None,
        is_active: bool = True,
        notes: str | None = None,
    ) -> SystemUserRow:
        """Upsert a system user row keyed by ``user_id``.

        Profile-only — credentials live in :meth:`put_credential`. The
        upsert preserves ``last_login_at`` on update (use
        :meth:`record_system_user_login` to bump it explicitly).
        """

    @abstractmethod
    async def get_system_user_by_id(self, user_id: UUID) -> SystemUserRow | None:
        """Look up a system user by primary key."""

    @abstractmethod
    async def get_system_user_by_username(self, username: str) -> SystemUserRow | None:
        """Look up a system user by the unique ``username`` index."""

    @abstractmethod
    async def count_system_users(self) -> int:
        """Total number of ``system_user`` rows.

        Backs the ``eyenet user create`` bootstrap path: a zero count means
        there is no operator to authenticate against yet, so the first
        ``create`` is allowed un-gated (and forced to ``role=admin``).
        """

    @abstractmethod
    async def record_system_user_login(
        self,
        *,
        user_id: UUID,
        at: datetime,
    ) -> SystemUserRow:
        """Bump ``last_login_at`` on a successful authentication. Raises
        :class:`ValueError` if the user doesn't exist."""

    # =================================================================
    # ESCAPE HATCH (collector-side custom transactions)
    # =================================================================

    @abstractmethod
    def session(self) -> Any:
        """Open an async session on the main engine.

        Returns an ``AsyncContextManager[AsyncSession]``. Use the typed
        flat methods first; this escape hatch is for transactions that
        can't be expressed as a single repo call (Matrix edit patching,
        reaction insertion).
        """

    # =================================================================
    # LIFECYCLE
    # =================================================================

    @property
    @abstractmethod
    def data_dir(self) -> Any:
        """The filesystem root the impl was constructed with (Path for
        SQLite, ignored for network-backed backends)."""

    @abstractmethod
    async def close(self) -> None:
        """Release all engines / pools / files held by this repository."""


__all__ = ["BaseRepository"]
