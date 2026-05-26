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
    from eyenet.contracts.attribution import LinkageRow
    from eyenet.contracts.audit import AuditLogRow
    from eyenet.contracts.case import CaseCollaboratorRow, CaseMemberRow, CaseRow
    from eyenet.contracts.clearance import SystemUserClearanceGrantRow
    from eyenet.contracts.enums import (
        CaseRoleOnCase,
        CaseSubjectKind,
        ClearanceScope,
        GroupKind,
        SensitivityTier,
        SourceDomainPatternKind,
        SourceKind,
        SystemLogLevel,
    )
    from eyenet.contracts.feedback import FeedbackPairRow
    from eyenet.contracts.message import AttachmentRow
    from eyenet.contracts.source import SourceRow
    from eyenet.contracts.source_domain import SourceDomainRow


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
    ) -> list[object]: ...

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
