"""Shared enums for EYENET contracts.

Single source of truth for every enum used across bus envelopes and DB rows.
Lives in `contracts/` so the build-gate test can introspect it without
importing the storage or service layers.
"""

from __future__ import annotations

from enum import StrEnum


class SourceKind(StrEnum):
    """Platform a `Source` row represents (MODELS §1.1)."""

    TELEGRAM = "telegram"
    MATRIX = "matrix"
    IRC = "irc"
    DISCORD = "discord"
    FORUM = "forum"
    RSS = "rss"
    XMPP = "xmpp"


class GroupKind(StrEnum):
    """Shape of a chat container (MODELS §1.3)."""

    CHAT = "chat"
    CHANNEL = "channel"
    DM = "dm"
    FORUM_THREAD = "forum_thread"
    IRC_CHANNEL = "irc_channel"
    MATRIX_ROOM = "matrix_room"


class IdentityState(StrEnum):
    """Operator-persona lifecycle (MODELS §2.1)."""

    AVAILABLE = "available"
    IN_USE = "in_use"
    COOLING = "cooling"
    FROZEN = "frozen"
    BURNED = "burned"


class MembershipRole(StrEnum):
    """Actor's role in a Group (MODELS §2.2)."""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"
    RESTRICTED = "restricted"
    BANNED = "banned"
    UNKNOWN = "unknown"


class ValueKind(StrEnum):
    """Persisted observation value discriminator (MODELS §2.3)."""

    HASH = "hash"
    NUMERIC = "numeric"
    ENUM_STR = "enum_str"
    ARRAY_STR = "array_str"
    ARRAY_NUMERIC = "array_numeric"


class LinkageState(StrEnum):
    """Linkage decision lifecycle (MODELS §2.5).

    Progression:
        PROPOSED   — automatic; linker output
        SUSPECTED  — operator triage; promoted from PROPOSED for closer look
        CONFIRMED  — operator decision; drives Persona aggregation
        REJECTED   — operator decision; terminal
        SUPERSEDED — admin; row replaced by a newer linkage (e.g. recomputed)

    Persona aggregation triggers ONLY on transition into CONFIRMED.
    SUSPECTED changes graph edge styling but not Persona membership.
    """

    PROPOSED = "proposed"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EngagementSubjectKind(StrEnum):
    """Discriminator for `EngagementAuthorization` (MODELS §2.13)."""

    ACTOR = "actor"
    GROUP = "group"


class EngagementScope(StrEnum):
    """Authorized engagement depth (MODELS §2.13)."""

    OBSERVE_ONLY = "observe_only"
    PASSIVE_ENGAGE = "passive_engage"
    ACTIVE_ENGAGE = "active_engage"


class CaseStatus(StrEnum):
    """Operator investigation lifecycle (API_PLAN §4.10.3 / MODELS §2.15).

    `archived` is terminal — reopening an archived case creates a NEW
    successor case via `parent_case_id`, never mutates the archived row.
    """

    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


class CaseSubjectKind(StrEnum):
    """Kind of row that can be a `case_member` subject (API_PLAN §4.10.1)."""

    OBSERVATION = "observation"
    ATTACHMENT = "attachment"
    MESSAGE = "message"
    ACTOR = "actor"
    PERSONA = "persona"
    LINKAGE = "linkage"


class CaseRoleOnCase(StrEnum):
    """A collaborator's role on a specific case (API_PLAN §4.10.1).

    Distinct from `SystemUserRole`: the latter is org-wide, this one is
    per-case. A user can be VIEWER org-wide and OWNER on a case.
    """

    OWNER = "owner"
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class RedundancyPolicy(StrEnum):
    """Per-Case collector-coverage policy for the discovery loop (API_PLAN §4.12).

    Governs whether a second collector may join a group an active collector
    already covers (the dedup/dual-cover dimension of the §4.12.3 eligibility
    predicate):

    - ``prefer_single`` (default) — skip the join if any collector is already
      in the group.
    - ``prefer_dual`` — allow a second collector when bandwidth permits; a
      third is skipped.
    - ``required_dual`` — refuse to operate on single coverage; alert on
      degradation. (The alerting half lands with the supervisor runtime.)
    """

    PREFER_SINGLE = "prefer_single"
    PREFER_DUAL = "prefer_dual"
    REQUIRED_DUAL = "required_dual"


class AutoJoinPolicy(StrEnum):
    """Per-Case automation posture for candidate approval (API_PLAN §4.12.1).

    ``disabled`` is the default for every new Case — auto-join is opt-in per
    investigation; there is no fleet-wide setting that quietly auto-expands.

    - ``disabled`` — every candidate is operator-triaged.
    - ``score_threshold`` — auto-approve when ``GroupCandidate.score`` crosses
      the Case ``auto_join_score_threshold`` AND eligibility passes.
    - ``score_threshold_with_role_gate`` — additionally require the mentioning
      actor's role signal to clear the gate.
    """

    DISABLED = "disabled"
    SCORE_THRESHOLD = "score_threshold"
    SCORE_THRESHOLD_WITH_ROLE_GATE = "score_threshold_with_role_gate"


class SensitivityTier(StrEnum):
    """Evidence sensitivity tier (API_PLAN §4.7).

    Promotable, never demotable. Default at ingest is `normal`. The classifier
    chain (§4.9.1) sets `classifier_tier` at ingest; operators may promote via
    `operator_tier_override` but never demote.
    """

    NORMAL = "normal"
    RESTRICTED = "restricted"
    CLASSIFIED = "classified"


class ClearanceScope(StrEnum):
    """Grant-only scopes flowing through the §4.8 grant lifecycle.

    Never present in any role baseline — every scope here MUST be granted
    explicitly with a bounded expiry (≤ 90 days) and a mandatory reason.

    - `READ_RESTRICTED` / `READ_CLASSIFIED` gate sensitive-evidence reads (§4.7).
    - `ADMIN_RECLASSIFY` authorises tier promotion (§4.9).
    - `ADMIN_CASE` authorises archive + administrative case actions (§4.10).
    """

    READ_RESTRICTED = "read:restricted"
    READ_CLASSIFIED = "read:classified"
    ADMIN_RECLASSIFY = "admin:reclassify"
    ADMIN_CASE = "admin:case"


class ReclassificationSubjectKind(StrEnum):
    """What kind of row is being reclassified (§4.9)."""

    OBSERVATION = "observation"
    ATTACHMENT = "attachment"


class FileServedVia(StrEnum):
    """How bytes were served — recorded in `file_access_journal` (§5.6)."""

    INLINE_JSON = "inline_json"
    ATTACHMENT_STREAM = "attachment_stream"
    THUMBNAIL_ONLY = "thumbnail_only"


class SystemUserRole(StrEnum):
    """Operator-tier role (MODELS §2.17)."""

    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class SystemLogLevel(StrEnum):
    """SystemLog row level — NOT debug/info (MODELS §2.18, PLAN §9.5)."""

    WARN = "warn"
    ERROR = "error"
    LIFECYCLE = "lifecycle"
    NOTICE = "notice"


class ConfidenceTier(StrEnum):
    """Operator-supplied label confidence (MODELS §2.12)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CERTAIN = "certain"


class AttachmentKind(StrEnum):
    """Attachment metadata kind (MODELS §2.9)."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    VOICE = "voice"
    OTHER = "other"


class InfrastructureKind(StrEnum):
    """Infrastructure artifact taxonomy (MODELS §2.7)."""

    WALLET_BTC = "wallet_btc"
    WALLET_XMR = "wallet_xmr"
    WALLET_ETH = "wallet_eth"
    PGP_KEY = "pgp_key"
    DOMAIN = "domain"
    ONION = "onion"
    EMAIL = "email"
    PHONE = "phone"
    HANDLE_OTHER_PLATFORM = "handle_other_platform"
    PASTE_URL = "paste_url"


class ActorAliasKind(StrEnum):
    """Alias history kind (MODELS §2.10)."""

    HANDLE = "handle"
    DISPLAY_NAME = "display_name"
    USERNAME = "username"


class SourceDomainPatternKind(StrEnum):
    """How a ``SourceDomain.pattern`` is matched against a hostname (MODELS §2.26).

    Specificity order for ``find_source_for_host``:
    ``exact`` > ``subdomain_wildcard`` > ``suffix_match``.

    Storage convention: ``pattern`` is stored post-normalize_host (lowercase
    ASCII punycode, no trailing dot, no ``*`` literal). For
    ``subdomain_wildcard``, the pattern holds **the parent only** — never the
    ``*.`` prefix; a CHECK at the SQL layer rejects any ``*`` in the column.

    Matching semantics:

    - ``exact "foo.com"`` matches **exactly** ``foo.com``.
    - ``subdomain_wildcard "foo.com"`` matches any strict subdomain
      (``x.foo.com``, ``a.b.foo.com``) but **not** ``foo.com`` itself.
    - ``suffix_match "foo.com"`` matches ``foo.com`` itself **and** any
      subdomain (strictly stronger than ``subdomain_wildcard``).
    """

    EXACT = "exact"
    SUBDOMAIN_WILDCARD = "subdomain_wildcard"
    SUFFIX_MATCH = "suffix_match"


class CollectorState(StrEnum):
    """In-process collector health state (PLAN §2.1).

    Reported by :class:`CollectorBase.health` — NOT persisted. The
    persisted lifecycle uses :class:`CollectorDesiredState` (operator
    intent) and :class:`CollectorObservedState` (supervisor reconcile).
    """

    STARTING = "starting"
    RUNNING = "running"
    COOLING = "cooling"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"
    STOPPED = "stopped"


class CollectorDesiredState(StrEnum):
    """Operator-expressed collector lifecycle intent (API_PLAN §4.11.2).

    The API mutates ``desired_state``; the supervisor reconciles to
    ``observed_state``. ``disabled`` is a hard stop the supervisor will
    refuse to start until an explicit operator transition to ``stopped``.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    DISABLED = "disabled"


class CollectorObservedState(StrEnum):
    """Supervisor-reported collector lifecycle state (API_PLAN §4.11.2).

    Supervisor-written, server-readable, **never** accepted in API
    request bodies. ``cooling`` is the post-crash backoff window;
    duration is ``min(2^restart_count, 600)`` seconds.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    COOLING = "cooling"
    CRASHED = "crashed"


class IdentityRole(StrEnum):
    """Identity's operational role in the discovery loop (API_PLAN §4.12).

    ``monitor`` is the long-running watcher (the default — every identity
    that observes traffic in an established group). ``scout`` is a
    short-lived probe that joins a freshly-approved
    :class:`GroupCandidate` and observes for 7 days before graduating to
    ``monitor`` (M9.E4). ``quarantine`` is a terminal role for identities
    that were detected/banned/burned during scout duty — they never
    re-enter rotation.
    """

    MONITOR = "monitor"
    SCOUT = "scout"
    QUARANTINE = "quarantine"


class CandidateState(StrEnum):
    """GroupCandidate lifecycle (MODELS §2.20).

    State machine (legal transitions in ``CandidatesMixin.transition_candidate``):

    .. code-block::

        discovered → queued → approved → joining → joined
                      │           │          │  │
                      ↓           ↓          ↓  └→ requested → joined
                   rejected    rejected   failed       │
                      │                     │          ↓
                      └──── parked ──────────┘     failed / parked
                                │
                                ↓ (re-entry, fresh operator decision)
                             approved

    ``requested`` (M9.E5.5): the collector sent a join *request* to an
    approval-gated group (telethon ``InviteRequestSentError``); it awaits a
    platform-side admin decision. Resolution (``requested → joined``) needs
    live membership detection — a follow-on; the entry + give-up edges land now.
    """

    DISCOVERED = "discovered"
    QUEUED = "queued"
    APPROVED = "approved"
    JOINING = "joining"
    JOINED = "joined"
    REQUESTED = "requested"
    REJECTED = "rejected"
    FAILED = "failed"
    PARKED = "parked"


class MentionKind(StrEnum):
    """How a GroupCandidateMention was observed (MODELS §2.21)."""

    INVITE_LINK = "invite_link"
    USERNAME_MENTION = "username_mention"
    FORWARD_ORIGIN = "forward_origin"
    LINK_PREVIEW = "link_preview"
    BIO_LINK = "bio_link"
    OTHER = "other"


class ResolutionState(StrEnum):
    """Bridge-resolution state for InfrastructureArtifact (MODELS §2.25).

    ``unresolved`` — no Source's SourceDomain matches the artifact's host yet.
    ``resolved`` — exactly one Source matches; ``resolved_to_source_id``
    populated. ``ambiguous`` — multiple Sources match (operator mistake;
    overlap detection in C1 should prevent this, but the state exists for
    defensive completeness). ``not_applicable`` — artifact ``kind`` carries
    no host (wallets, PGP keys, emails, phones, etc.).
    """

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"


class ArtifactSubjectKind(StrEnum):
    """GroupAccessArtifact subject discriminator (MODELS §2.24)."""

    GROUP = "group"
    CANDIDATE = "candidate"


class GroupAccessKind(StrEnum):
    """Platform-neutral access-vector taxonomy (MODELS §2.24).

    Preference ordering (lowest = cheapest / lowest OPSEC cost / most stable):
    public_identifier < invite_link < qr_code < direct_invite <
    paid_subscription < restricted_other. ``access_blocked`` is a known-bad
    state — the artifact records that access is denied for this identity.
    """

    PUBLIC_IDENTIFIER = "public_identifier"
    INVITE_LINK = "invite_link"
    QR_CODE = "qr_code"
    DIRECT_INVITE = "direct_invite"
    PAID_SUBSCRIPTION = "paid_subscription"
    ACCESS_BLOCKED = "access_blocked"
    RESTRICTED_OTHER = "restricted_other"


class ArtifactValidationState(StrEnum):
    """GroupAccessArtifact validation lifecycle (MODELS §2.24)."""

    UNVERIFIED = "unverified"
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    USAGE_EXHAUSTED = "usage_exhausted"
    BLOCKED_FOR_OUR_IDENTITY = "blocked_for_our_identity"
    UNKNOWN_FAILURE = "unknown_failure"


class JoinedVia(StrEnum):
    """How a CollectorGroupMembership was established (MODELS §2.22).

    ``seed`` — operator-configured initial scope at collector startup.
    ``candidate`` — came through the §2.20-§2.21 discovery loop;
    ``joined_via_candidate_id`` is populated. ``manual`` — operator added
    mid-investigation via the UI. ``restored`` — collector was banned, a
    replacement identity rejoined the same group.
    """

    SEED = "seed"
    CANDIDATE = "candidate"
    MANUAL = "manual"
    RESTORED = "restored"


__all__ = [
    "ActorAliasKind",
    "ArtifactSubjectKind",
    "ArtifactValidationState",
    "AttachmentKind",
    "AutoJoinPolicy",
    "CandidateState",
    "CaseRoleOnCase",
    "CaseStatus",
    "CaseSubjectKind",
    "ClearanceScope",
    "CollectorDesiredState",
    "CollectorObservedState",
    "CollectorState",
    "ConfidenceTier",
    "EngagementScope",
    "EngagementSubjectKind",
    "FileServedVia",
    "GroupAccessKind",
    "GroupKind",
    "IdentityRole",
    "IdentityState",
    "InfrastructureKind",
    "JoinedVia",
    "LinkageState",
    "MembershipRole",
    "MentionKind",
    "ReclassificationSubjectKind",
    "RedundancyPolicy",
    "ResolutionState",
    "SensitivityTier",
    "SourceDomainPatternKind",
    "SourceKind",
    "SystemLogLevel",
    "SystemUserRole",
    "ValueKind",
]
