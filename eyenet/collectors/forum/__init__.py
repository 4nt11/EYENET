# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum collectors (SourceKind.FORUM).

Engine-specific parsers live in underscore-prefixed modules and are re-exported
here. The engine (MyBB, phpBB, ...) is a collector/source_config detail, not a
distinct SourceKind: every forum is ``SourceKind.FORUM``.
"""

from __future__ import annotations

from eyenet.collectors.forum._mybb import ParsedPost, parse_thread, thread_page_count

__all__ = ["ParsedPost", "parse_thread", "thread_page_count"]
