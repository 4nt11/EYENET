# SPDX-License-Identifier: AGPL-3.0-or-later
"""MyBB thread parser unit tests (against a synthetic, PII-free fixture)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from eyenet.collectors.forum import (
    parse_forum_links,
    parse_reply_form,
    parse_thread,
    parse_thread_links,
    thread_page_count,
)

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


def test_parse_forum_links_dedupes_and_orders() -> None:
    html = (
        "<a href='Forum-Databases'>db</a>"
        "<a href='https://b.test/Forum-Leaks--3'>leaks</a>"
        "<a href='Forum-Databases?foo=1'>db again</a>"  # same path, deduped
        "<a href='Thread-x--1'>not a forum</a>"
    )
    assert parse_forum_links(html) == ["Forum-Databases", "https://b.test/Forum-Leaks--3"]


def test_parse_thread_links_strips_query_and_dedupes() -> None:
    html = (
        "<a href='Thread-a--1?pid=5#pid5'>a</a>"
        "<a href='Thread-a--1'>a again</a>"  # dedupes to the same canonical path
        "<a href='Thread-b--2?action=lastpost'>b</a>"
        "<a href='Forum-X'>not a thread</a>"
    )
    assert parse_thread_links(html) == ["Thread-a--1", "Thread-b--2"]


def test_parse_reply_form_scrapes_tokens() -> None:
    html = (
        '<form action="newreply.php?tid=92204&processed=1" method="post">'
        '<input type="hidden" name="my_post_key" value="878c614c4935" />'
        '<input type="hidden" name="posthash" value="3e0e812884b8" />'
        '<input type="hidden" name="tid" value="92204" />'
        '<input type="hidden" name="subject" value="RE: leak thread" />'
        '<textarea name="message"></textarea></form>'
    )
    form = parse_reply_form(html)
    assert form is not None
    assert form.my_post_key == "878c614c4935"
    assert form.posthash == "3e0e812884b8"
    assert form.tid == "92204"
    assert form.subject == "RE: leak thread"


def test_parse_reply_form_missing_tokens_returns_none() -> None:
    # no my_post_key -> fail closed, never POST without the CSRF token
    assert parse_reply_form('<form><input name="tid" value="1"></form>') is None


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


def test_quote_stripped_from_classifier_text_but_kept_in_html() -> None:
    # a reply that quotes a breach dump, then says one word
    html = (
        '<div class="post classic" id="post_7">'
        '<div class="post_user-profile"><a href="User-x">x</a></div>'
        '<span class="post_date">01-02-26, 09:30 AM</span>'
        '<div class="post_body">'
        '<blockquote class="mycode_quote"><cite>david20 Wrote:</cite>'
        "235K+ records breach dump sample email:pass leaked</blockquote>"
        "interresting</div></div>"
    )
    (post,) = parse_thread(html)
    # classifier text = the poster's own word only, NOT the quoted breach dump
    assert post.body_text == "interresting"
    assert "235K" not in post.body_text
    assert "breach" not in post.body_text
    # evidence HTML keeps the full quote
    assert "235K+ records" in post.body_html
    assert "mycode_quote" in post.body_html


def test_reply_gated_detection(posts: list) -> None:
    # the synthetic fixture has no [hide] gate
    assert all(p.reply_gated is False for p in posts)
    gated = (
        '<div class="post classic" id="post_5">'
        '<div class="post_user-profile"><a href="User-x">x</a></div>'
        '<span class="post_date">01-02-26, 09:30 AM</span>'
        '<div class="post_body">Hidden Content. You must reply to this thread to '
        "view this content or upgrade your account.</div></div>"
    )
    (post,) = parse_thread(gated)
    assert post.reply_gated is True


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


def _cf_encode(email: str, key: int = 0x2b) -> str:
    return bytes([key, *[ord(c) ^ key for c in email]]).hex()


def test_cloudflare_email_decoded() -> None:
    email = "victim@leak.io"
    html = (
        '<div class="post classic" id="post_3">'
        '<div class="post_user-profile"><a href="User-x">x</a></div>'
        '<span class="post_date">01-02-26, 09:30 AM</span>'
        '<div class="post_body">contact <a class="__cf_email__" '
        f'href="/cdn-cgi/l/email-protection" data-cfemail="{_cf_encode(email)}">'
        '[email\u00a0protected]</a></div></div>'
    )
    (post,) = parse_thread(html)
    assert email in post.body_text
    assert email in post.body_html
    assert "cf_email" not in post.body_html  # the obfuscation element is gone
