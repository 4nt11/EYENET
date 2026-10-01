# SPDX-License-Identifier: AGPL-3.0-or-later
"""XenForo parser + the engine-dispatch seam (`get_parser`, `posted_at_to_utc`).

Fixtures are trimmed but structurally faithful to a real XenForo board with
CUSTOM friendly-URL routes (`/foros/`, `/post/`) and a Spanish locale - the two
traps the parser must survive without hardcoding English routes or label text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from eyenet.collectors.forum import (
    _mybb,
    _xenforo,
    get_parser,
    posted_at_to_utc,
)

_FIX = Path(__file__).resolve().parents[2] / "fixtures"
_THREAD = (_FIX / "xenforo_thread.html").read_text(encoding="utf-8")
_BOARD = (_FIX / "xenforo_board.html").read_text(encoding="utf-8")
_INDEX = (_FIX / "xenforo_index.html").read_text(encoding="utf-8")


@pytest.mark.unit
def test_parse_thread_posts_author_and_pid() -> None:
    posts = _xenforo.parse_thread(_THREAD)
    assert len(posts) == 2
    assert posts[0].author_username == "werty"
    assert posts[0].author_display == "werty"
    assert posts[0].pid == "100"
    assert posts[0].edited is True
    assert posts[1].author_username == "segundo"
    assert posts[1].pid == "101"
    assert posts[1].edited is False


@pytest.mark.unit
def test_parse_thread_timestamps_are_tz_aware() -> None:
    posts = _xenforo.parse_thread(_THREAD)
    # ISO datetime attr carries the real +01:00 offset -> aware, offset preserved.
    assert posts[0].posted_at is not None
    assert posts[0].posted_at.utcoffset() is not None
    assert posts[0].posted_at.utcoffset().total_seconds() == 3600  # type: ignore[union-attr]
    # Second post has only data-time epoch -> aware UTC via fallback.
    assert posts[1].posted_at is not None
    assert posts[1].posted_at.tzinfo is not None
    assert posts[1].posted_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


@pytest.mark.unit
def test_parse_thread_strips_quotes_from_body_text_only() -> None:
    post = _xenforo.parse_thread(_THREAD)[0]
    # Classifier text must be the poster's OWN words...
    assert "MY_OWN_WORDS" in post.body_text
    assert "QUOTED_FROM_SOMEONE_ELSE" not in post.body_text
    # ...but the evidence HTML keeps the quote verbatim.
    assert "QUOTED_FROM_SOMEONE_ELSE" in post.body_html
    assert "bbCodeBlock--quote" in post.body_html


@pytest.mark.unit
def test_parse_thread_title_and_tid_and_pages() -> None:
    assert _xenforo.parse_thread_title(_THREAD) == "Thread Subject"
    assert _xenforo.parse_canonical_tid(_THREAD) == "60371"
    assert _xenforo.thread_page_count(_THREAD) == 3


@pytest.mark.unit
def test_thread_links_keep_custom_post_route() -> None:
    links = _xenforo.parse_thread_links(_BOARD)
    assert links == ["/post/primer-hilo.111/", "/post/segundo-hilo.222/"]
    assert all(link.startswith("/post/") for link in links)


@pytest.mark.unit
def test_forum_links_scope_to_forum_nodes_and_keep_custom_route() -> None:
    links = _xenforo.parse_forum_links(_INDEX)
    # Only the two node--forum entries, NOT the node--category header.
    assert links == ["/foros/novedades/", "/foros/hacking/"]
    assert all(link.startswith("/foros/") for link in links)


@pytest.mark.unit
def test_subforum_links_are_scoped_to_the_inline_list() -> None:
    assert _xenforo.parse_subforum_links(_INDEX) == ["/foros/anuncios.9/"]


@pytest.mark.unit
def test_get_parser_dispatch_is_case_insensitive_and_fails_loud() -> None:
    assert get_parser("xenforo") is _xenforo
    assert get_parser("MyBB") is _mybb
    with pytest.raises(ValueError, match="unknown forum engine"):
        get_parser("phpbb")


@pytest.mark.unit
def test_posted_at_to_utc_converts_aware_and_attaches_naive() -> None:
    # aware +01:00 02:07 -> 01:07 UTC (converted, NOT clobbered)
    aware = datetime(2022, 12, 28, 2, 7, 7, tzinfo=timezone(timedelta(hours=1)))
    out = posted_at_to_utc(aware)
    assert out is not None
    assert out.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert out.hour == 1 and out.minute == 7
    # naive -> UTC attached, wall clock unchanged
    naive = datetime(2022, 12, 28, 2, 7, 7)  # noqa: DTZ001
    out2 = posted_at_to_utc(naive)
    assert out2 is not None and out2.hour == 2 and out2.tzinfo is UTC
    assert posted_at_to_utc(None) is None
