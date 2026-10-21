# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shape contract for the render layer — no network, no mcp SDK needed.

If these pass, the tools return hit lines + compact records instead of JSON,
which is the entire reason eyenet-mcp exists.
"""

from __future__ import annotations

import base64

from eyenet_mcp.render import (
    hit_line,
    offset_to_cursor,
    parse_handle,
    record_text,
    render_search,
    resource_for,
)


def test_hit_line_is_handle_title_snippet() -> None:
    line = hit_line({"entity_type": "actor", "entity_id": "u1", "title": "mr_robot", "kind": "known"})
    assert line.startswith("actor:u1  mr_robot")
    assert "known" in line  # falls back to kind when no subtitle


def test_render_search_appends_next_only_when_more() -> None:
    page = {
        "items": [{"entity_type": "artifact", "entity_id": "a1", "title": "btc addr"}],
        "next_cursor": "Mg==",
    }
    out = render_search(page)
    assert out.splitlines()[0].startswith("artifact:a1")
    assert out.splitlines()[-1] == "next:Mg=="
    assert render_search({"items": []}) == "no hits"
    assert "next:" not in render_search({"items": page["items"]})


def test_record_text_tiers() -> None:
    # nested like a MessageDetail: body (display) + body_html (evidence)
    obj = {
        "source_display": "forum:x",
        "message": {"author": "nobody", "body": "b" * 5000, "body_html": "<p>raw</p>"},
        "deleted": None,
    }
    terse = record_text("message", obj)
    assert "author: nobody" in terse  # nested dict flattened one level
    assert "deleted" not in terse  # None dropped
    assert "b" * 5000 not in terse  # body snippeted in terse
    assert "<omitted" in terse and "body_html" in terse  # evidence omitted...
    assert "<p>raw</p>" not in terse

    full = record_text("message", obj, full=True)
    assert "b" * 5000 in full  # sanitized body shown in full
    assert "<p>raw</p>" not in full  # ...but full still withholds raw body_html
    assert "<omitted" in full

    ev = record_text("message", obj, evidence=True)
    assert "<p>raw</p>" in ev  # evidence unlocks the raw field


def test_record_text_caps_even_full_and_normalizes_nbsp() -> None:
    # NBSP (un-backfilled forum rows) renders as a space, not \xa0 soup
    assert record_text("message", {"body": "a\xa0\xa0b"}) == "# message\nbody: a  b"
    # a leak-dump body is capped even in full, with a tail count — never a bomb
    full = record_text("message", {"body": "z" * 20000}, full=True)
    assert "z" * 20000 not in full
    assert "+12000 chars)" in full  # 20000 - 8000 cap


def test_parse_handle_and_resource_mapping() -> None:
    assert parse_handle("actor:abc-123") == ("actor", "abc-123")
    assert resource_for("persona") == "personas"
    assert resource_for("widget") == "widgets"  # naive plural fallback
    for bad in ("noselector", ":noid", "nokind:"):
        try:
            parse_handle(bad)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"{bad!r} should have raised")


def test_offset_cursor_matches_api_encoding() -> None:
    assert offset_to_cursor(0) is None
    cur = offset_to_cursor(40)
    assert cur is not None
    assert base64.urlsafe_b64decode(cur).decode() == "40"
