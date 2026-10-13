# SPDX-License-Identifier: AGPL-3.0-or-later
"""Group-liveness classifier — maps a telethon resolve failure onto a verdict.

A monitored group can be nuked platform-side (deleted, TOS-banned, renamed). The
collector already resolves group identifiers on its hot paths; this turns the
*class name* of a resolve failure into a liveness verdict, so the caller can
transition the candidate → DEAD and stop monitoring (see
``eyenet.contracts.enums.CandidateState.DEAD``).

Pure and import-free (switches on ``type(exc).__name__``, a plain string) so it
is testable without telethon — same pattern as ``_join.classify_join_error``.
Policy: HARD SIGNAL ONLY. Only an unambiguous "this group is gone" error marks a
group dead. A silent-empty backfill (0 messages) is NOT a death signal — a quiet
but live channel is indistinguishable — so it never reaches here.
"""

from __future__ import annotations

from enum import Enum


class GroupLiveness(Enum):
    """Verdict for a monitored group after a resolve attempt.

    The non-ALIVE values double as the membership ``left_reason`` (all well under
    the 64-char column limit).
    """

    ALIVE = "alive"
    # Username no longer exists / is unacceptable (UsernameNotOccupiedError,
    # UsernameInvalidError) or telethon could not resolve the identifier at all
    # (plain ValueError — its documented signal for a deleted/renamed username).
    DELETED = "channel_deleted"
    # ChannelPrivateError: banned / deleted / we were removed. From a member
    # vantage these are indistinguishable; the group is unreachable either way.
    UNAVAILABLE = "channel_unavailable"


# Hard "the group is gone" signals. Unknown/transient errors (FloodWaitError,
# timeouts, RPC hiccups) deliberately fall through to ALIVE — we never kill a
# group on an error we do not understand.
_DELETED_ERRORS = frozenset({"UsernameNotOccupiedError", "UsernameInvalidError", "ValueError"})
_UNAVAILABLE_ERRORS = frozenset({"ChannelPrivateError"})


def classify_liveness(exc_name: str | None) -> GroupLiveness:
    """Map a telethon exception *class name* (or ``None`` on success) to a verdict.

    ``None`` — the resolve succeeded — is ALIVE. An unrecognized error name is
    ALIVE too (conservative: a transient failure must not nuke a live group).
    """
    if exc_name is None:
        return GroupLiveness.ALIVE
    if exc_name in _DELETED_ERRORS:
        return GroupLiveness.DELETED
    if exc_name in _UNAVAILABLE_ERRORS:
        return GroupLiveness.UNAVAILABLE
    return GroupLiveness.ALIVE


__all__ = ["GroupLiveness", "classify_liveness"]
