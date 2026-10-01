# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forum collectors (SourceKind.FORUM).

Engine-specific parsers live in underscore-prefixed modules (``_mybb``,
``_xenforo``, ...). The engine (MyBB, XenForo, ...) is a collector/source_config
detail, not a distinct SourceKind: every forum is ``SourceKind.FORUM``.

:func:`get_parser` is the single dispatch point (mirrors the storage factory):
a collector/stub selects its parser module by engine name and calls the flat
functions on it, so adding an engine is one entry here, not edits at every call
site. The package also re-exports the MyBB surface directly for back-compat with
callers written before the dispatch existed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

from eyenet.collectors.forum import _mybb, _xenforo
from eyenet.collectors.forum._mybb import (
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
from eyenet.collectors.forum._post import ParsedPost

if TYPE_CHECKING:
    from collections.abc import Sequence


class ForumParser(Protocol):
    """The engine-agnostic parser surface a collector/stub consumes.

    Modules ``_mybb`` and ``_xenforo`` satisfy this structurally. Engine-specific
    extras (each engine's own ``ReplyForm`` / ``parse_reply_form``) are NOT part
    of the shared surface; a caller that needs them imports the concrete module.
    """

    def parse_thread(self, html: str) -> list[ParsedPost]: ...
    def parse_thread_links(self, html: str) -> Sequence[str]: ...
    def parse_forum_links(self, html: str) -> Sequence[str]: ...
    def parse_subforum_links(self, html: str) -> Sequence[str]: ...
    def parse_canonical_tid(self, html: str) -> str | None: ...
    def parse_thread_title(self, html: str) -> str | None: ...
    def thread_page_count(self, html: str) -> int: ...


# The modules structurally satisfy ForumParser; mypy can't verify a module
# against a Protocol in a dict literal, so cast at the single registration point.
_PARSERS: dict[str, ForumParser] = {
    "mybb": cast("ForumParser", _mybb),
    "xenforo": cast("ForumParser", _xenforo),
}


def get_parser(engine: str) -> ForumParser:
    """Return the parser module for ``engine`` (case-insensitive).

    Raises ValueError on an unknown engine so a misconfigured source fails loud
    at construction, not with silent empty parses later.
    """
    try:
        return _PARSERS[engine.lower()]
    except KeyError:
        known = ", ".join(sorted(_PARSERS))
        raise ValueError(f"unknown forum engine {engine!r}; known: {known}") from None


def posted_at_to_utc(dt: datetime | None) -> datetime | None:
    """Normalize a :attr:`ParsedPost.posted_at` to UTC, engine-agnostically.

    - aware (XenForo emits a real offset) -> CONVERT to UTC (astimezone). Using
      ``.replace(tzinfo=UTC)`` here would clobber the offset and shift the time.
    - naive (MyBB board-local) -> ATTACH UTC (the board-UTC assumption; the true
      offset is a per-source calibration knob, same as before).
    - None (unparsed/relative date) -> None; the caller falls back to now().
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    return dt.replace(tzinfo=UTC)


__all__ = [
    "ForumParser",
    "ParsedPost",
    "ReplyForm",
    "get_parser",
    "parse_canonical_tid",
    "parse_forum_links",
    "parse_reply_form",
    "parse_subforum_links",
    "parse_thread",
    "parse_thread_links",
    "parse_thread_title",
    "posted_at_to_utc",
    "thread_page_count",
]
