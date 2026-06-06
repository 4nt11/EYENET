# SPDX-License-Identifier: AGPL-3.0-or-later
"""`channel_reference_extraction` discovery extractor (API_PLAN §4.12, M9.E2).

Detects platform-native references to *other* groups in a message and records
a :class:`~eyenet.models.candidates.GroupCandidateMention` for each — the raw
material the triage queue + scorer feed on. A reference observed in a group at
``depth_from_root = d`` produces a mention at ``d + 1`` (one hop further from the
seed root), carrying the same ``seed_root_id`` — this is the depth propagation
the discovery tree relies on.

Idempotency is the storage layer's: ``record_candidate_mention`` is keyed on
``(candidate, mention_evidence_ref)``, and we build a stable evidence ref of
``{message evidence_ref}#{reference}`` so a redelivered message never
double-records.

Detected forms (platform-neutral on purpose — one extractor, many sources):
- Telegram invite links ``t.me/+<hash>`` / ``t.me/joinchat/<hash>`` → INVITE_LINK
- Telegram public links / @handles ``t.me/<name>`` / ``@<name>``      → USERNAME_MENTION
- Matrix room aliases ``#room:server`` (and ``matrix.to/#/#room:server``) → USERNAME_MENTION
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from eyenet.contracts.enums import MentionKind
from eyenet.telemetry.logging import get_logger

from ._base import DiscoveryExtractor

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository

    from ._base import MessageContext

_log = get_logger()


class _Reference(NamedTuple):
    """One detected group reference: its candidate key + how it was seen."""

    platform_groupid: str
    kind: MentionKind


# Telegram invite links: t.me/+HASH or t.me/joinchat/HASH (the group id is
# unknown until joined — the invite hash is the candidate key).
_TG_INVITE_RE = re.compile(
    r"(?:https?://)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]{8,})", re.IGNORECASE
)
# Telegram public channel/user links: t.me/NAME (not joinchat/+).
_TG_PUBLIC_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})\b", re.IGNORECASE)
# Bare @handles (Telegram-style). 5-32 chars per Telegram username rules.
_AT_HANDLE_RE = re.compile(r"(?<![\w/])@([A-Za-z][A-Za-z0-9_]{4,31})\b")
# Matrix room aliases: #room:server (optionally wrapped in a matrix.to link).
_MATRIX_ALIAS_RE = re.compile(
    r"(?:https?://matrix\.to/#/)?(#[A-Za-z0-9._=\-/]+:[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
)


def _detect(text: str) -> set[_Reference]:
    """Return the distinct group references in ``text``."""
    refs: set[_Reference] = set()
    for m in _TG_INVITE_RE.finditer(text):
        refs.add(_Reference(f"joinchat:{m.group(1)}", MentionKind.INVITE_LINK))
    for m in _TG_PUBLIC_RE.finditer(text):
        refs.add(_Reference(f"@{m.group(1).lower()}", MentionKind.USERNAME_MENTION))
    for m in _AT_HANDLE_RE.finditer(text):
        refs.add(_Reference(f"@{m.group(1).lower()}", MentionKind.USERNAME_MENTION))
    for m in _MATRIX_ALIAS_RE.finditer(text):
        refs.add(_Reference(m.group(1).lower(), MentionKind.USERNAME_MENTION))
    return refs


class ChannelReferenceExtractor(DiscoveryExtractor):
    """Record GroupCandidateMentions for group references in a message (M9.E2)."""

    name = "channel_reference_extraction"

    async def process(self, ctx: MessageContext, storage: BaseRepository) -> int:
        refs = _detect(ctx.text)
        # The reference is one hop further from the root than the group it was
        # seen in; the seed root is inherited from that group's lineage.
        child_depth = ctx.depth_from_root + 1
        recorded = 0
        for ref in refs:
            # Don't record a self-reference to the group the message is in.
            if ref.platform_groupid == str(ctx.observed_in_group_id):
                continue
            candidate, _ = await storage.record_candidate_mention(
                source_id=ctx.source_id,
                platform_groupid=ref.platform_groupid,
                observed_by_collector_id=ctx.observed_by_collector_id,
                observed_in_group_id=ctx.observed_in_group_id,
                seed_root_id=ctx.seed_root_id,
                depth_from_root=child_depth,
                mention_evidence_ref=f"{ctx.evidence_ref}#{ref.platform_groupid}",
                mention_kind=ref.kind,
                mentioned_at_source=ctx.sent_at_source,
                mentioned_at_ingest=ctx.collected_at,
                mentioning_actor_id=ctx.mentioning_actor_id,
            )
            # §4.12.2 step 3: recompute the candidate score on the new mention
            # (this also runs the step-4 auto-queue if a Case threshold is set).
            await storage.score_candidate(candidate.id)
            recorded += 1
        if recorded:
            _log.debug(
                "channel_reference_extraction.recorded",
                count=recorded,
                depth=child_depth,
                observed_in_group_id=str(ctx.observed_in_group_id),
            )
        return recorded


__all__ = ["ChannelReferenceExtractor"]
