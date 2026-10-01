# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shared :class:`ParsedPost` contract.

One post, engine-independent. Every forum parser (``_mybb``, ``_xenforo``, future
``_phpbb`` ...) produces this same shape, so the collector and the stub consume a
single type regardless of which board engine produced the HTML.

Note the ``posted_at`` convention is *per engine* and documented on each parser:
MyBB yields board-local NAIVE datetimes (the collector attaches the source tz),
XenForo yields TZ-AWARE datetimes (it emits the real offset). Use
:func:`eyenet.collectors.forum.posted_at_to_utc` to normalize either to UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ParsedPost:
    """One post extracted from a forum thread page."""

    pid: str
    author_username: str  # the actor_key seed (board-stable handle/slug)
    author_display: str  # name as shown
    posted_at: datetime | None  # naive (MyBB) or aware (XenForo); None if unparsed
    posted_raw: str  # date string exactly as rendered (audit)
    edited: bool
    body_text: str  # tags stripped, quotes removed, for the classifier
    body_html: str  # inner HTML of the post body, evidence-faithful
    reply_gated: bool  # body carries a hidden/reply-to-view block


__all__ = ["ParsedPost"]
