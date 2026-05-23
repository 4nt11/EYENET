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


class CaseState(StrEnum):
    """Operator investigation lifecycle (MODELS §2.15)."""

    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"


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


class CollectorState(StrEnum):
    """Collector health state (PLAN §2.1)."""

    STARTING = "starting"
    RUNNING = "running"
    COOLING = "cooling"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"
    STOPPED = "stopped"


__all__ = [
    "ActorAliasKind",
    "AttachmentKind",
    "CaseState",
    "CollectorState",
    "ConfidenceTier",
    "EngagementScope",
    "EngagementSubjectKind",
    "GroupKind",
    "IdentityState",
    "InfrastructureKind",
    "LinkageState",
    "MembershipRole",
    "SourceKind",
    "SystemLogLevel",
    "SystemUserRole",
    "ValueKind",
]
