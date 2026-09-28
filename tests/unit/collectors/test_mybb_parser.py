# SPDX-License-Identifier: AGPL-3.0-or-later
"""MyBB thread parser unit tests (against a synthetic, PII-free fixture)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from eyenet.collectors.forum import parse_thread, thread_page_count

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "mybb_thread.html"


@pytest.fixture
def posts() -> list:
    return parse_thread(_FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_post_in_order(posts: list) -> None:
    assert [p.pid for p in posts] == ["1001", "1002"]


def test_author_username_is_the_user_slug(posts: list) -> None:
    # slug from /User-<slug>, not the avatar link or the icon anchor
    assert posts[0].author_username == "alice"
    assert posts[1].author_username == "bob_99"
    assert posts[0].author_display == "alice"


def test_board_local_date_is_day_first(posts: list) -> None:
    # 01-02-26 -> 1 Feb 2026 (DD-MM-YY), naive/board-local
    assert posts[0].posted_at == datetime(2026, 2, 1, 9, 30)  # noqa: DTZ001
    assert posts[1].posted_at == datetime(2026, 2, 2, 23, 45)  # noqa: DTZ001
    assert posts[0].posted_raw == "01-02-26, 09:30 AM"


def test_edited_flag(posts: list) -> None:
    assert posts[0].edited is False  # empty post_edit span
    assert posts[1].edited is True  # non-empty "last modified" note


def test_body_text_strips_tags_but_keeps_content(posts: list) -> None:
    assert "Hello" in posts[0].body_text
    assert "world" in posts[0].body_text
    assert "<strong>" not in posts[0].body_text


def test_body_html_is_evidence_faithful(posts: list) -> None:
    assert "<strong>world</strong>" in posts[0].body_html


def test_thread_page_count() -> None:
    # no pagination block -> single page
    assert thread_page_count("<html><body><div class='post'></div></body></html>") == 1
    paged = (
        '<div class="pagination">'
        '<a class="pagination_page" href="Thread-x--9?page=2">2</a>'
        '<a class="pagination_page" href="Thread-x--9?page=7">7</a>'
        '<a class="pagination_next" href="Thread-x--9?page=3">next</a>'
        "</div>"
    )
    assert thread_page_count(paged) == 7


def test_unparseable_date_yields_none_not_crash() -> None:
    html = (
        '<div class="post classic" id="post_9">'
        '<div class="post_user-profile"><a href="User-x">x</a></div>'
        '<span class="post_date">Today, 10:56 PM</span>'
        '<div class="post_body">hi</div></div>'
    )
    (post,) = parse_thread(html)
    assert post.posted_at is None
    assert post.posted_raw == "Today, 10:56 PM"
