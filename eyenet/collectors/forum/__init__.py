# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum collectors (SourceKind.FORUM).

Engine-specific parsers live in underscore-prefixed modules and are re-exported
here. The engine (MyBB, phpBB, ...) is a collector/source_config detail, not a
distinct SourceKind: every forum is ``SourceKind.FORUM``.
"""

from __future__ import annotations

from eyenet.collectors.forum._mybb import (
    ParsedPost,
    ReplyForm,
    parse_canonical_tid,
    parse_forum_links,
    parse_reply_form,
    parse_subforum_links,
    parse_thread,
    parse_thread_links,
    parse_thread_title,
    thread_page_count,
)

__all__ = [
    "ParsedPost",
    "ReplyForm",
    "parse_canonical_tid",
    "parse_forum_links",
    "parse_reply_form",
    "parse_subforum_links",
    "parse_thread",
    "parse_thread_links",
    "parse_thread_title",
    "thread_page_count",
]
