# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure rendering + handle plumbing — no network, no mcp import.

Kept separate from server.py precisely so the shape contract is unit-testable
without a live API or the mcp SDK installed (test_mcp_shape.py hits only this).
"""

from __future__ import annotations

import base64
from typing import Any

# entity_type -> /v1 resource path. Naive plural fallback for the rest.
# ponytail: explicit only for the kinds whose plural isn't +"s"; grow when a
# `get` 404s on a kind that should resolve.
_RESOURCE = {
    "actor": "actors",
    "message": "messages",
    "thread": "threads",
    "persona": "personas",
    "artifact": "artifacts",
    "incident": "incidents",
    "indicator": "indicators",
    "linkage": "linkages",
    "case": "cases",
    "source": "sources",
    "document": "documents",
    "crew": "crews",
    "group": "groups",
    "identity": "identities",
}

# Evidence/noise fields — omitted unless full=True. `body` is NOT here: it is the
# plaintext display projection we DO want; `body_html` is the raw evidence we don't.
_HEAVY = {"body_html", "source_specific", "attachments", "fields", "raw", "content"}

_SNIPPET = 120
_VALUE = 200
# Even full=True caps each value — a single leak-dump body must not blow the budget.
_FULL_CAP = 8000


def resource_for(kind: str) -> str:
    """Map an entity_type to its /v1 collection path."""
    return _RESOURCE.get(kind, f"{kind}s")  # ponytail: naive pluralize fallback


def parse_handle(handle: str) -> tuple[str, str]:
    """Split a `kind:id` handle. Raises ValueError on a malformed handle."""
    kind, sep, ident = handle.partition(":")
    if not sep or not kind or not ident:
        raise ValueError(f"malformed handle {handle!r} — want 'kind:id'")
    return kind, ident


def offset_to_cursor(offset: int) -> str | None:
    """Encode an integer offset as the API's opaque base64url cursor.

    Mirrors eyenet.api.deps_paging.encode_cursor. ponytail: couples us to that
    encoding; if the API ever switches to keyset, pass next_cursor through
    verbatim instead of synthesizing from an int.
    """
    if offset <= 0:
        return None
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def hit_line(item: dict[str, Any]) -> str:
    """One `kind:id  title — snippet` line from a SearchHit."""
    handle = f"{item.get('entity_type', '?')}:{item.get('entity_id', '?')}"
    title = (item.get("title") or "").strip()
    sub = (item.get("subtitle") or item.get("kind") or "").strip()
    line = f"{handle}  {title}".rstrip()
    if sub:
        line += f"  — {sub[:_SNIPPET]}"
    return line


def render_search(page: dict[str, Any]) -> str:
    """A search page -> hit lines + a trailing `next:` cursor when there's more."""
    items = page.get("items") or []
    if not items:
        return "no hits"
    lines = [hit_line(i) for i in items]
    nxt = page.get("next_cursor")
    if nxt:
        lines.append(f"next:{nxt}")
    return "\n".join(lines)


def _clip(text: str, cap: int) -> str:
    """NBSP (un-backfilled forum rows) -> space for display, then cap with a tail
    count so a single leak-dump field can never blow the context budget."""
    text = text.replace("\xa0", " ")
    return f"{text[:cap]}…(+{len(text) - cap} chars)" if len(text) > cap else text


def record_text(
    kind: str, obj: dict[str, Any], *, full: bool = False, evidence: bool = False
) -> str:
    """A record -> compact `key: value` lines, nested dicts flattened one level.

    Three tiers: terse (default) snippets each value; full shows the sanitized
    fields (e.g. the plaintext `body`) in full; evidence additionally unlocks the
    raw evidence fields (`body_html`, `source_specific`). Every value is capped
    either way — the MCP is a token lens, never a hauler of raw evidence."""
    expanded = full or evidence
    cap = _FULL_CAP if expanded else _VALUE
    out = [f"# {kind}"]

    def emit(key: str, value: Any, prefix: str = "") -> None:
        if value is None:
            return
        if key in _HEAVY and not evidence:
            out.append(f"{prefix}{key}: <omitted; evidence=true for the raw field>")
            return
        if isinstance(value, dict):
            out.append(f"{prefix}{key}:")
            for k, v in value.items():
                emit(k, v, prefix + "  ")
            return
        out.append(f"{prefix}{key}: {_clip(str(value), cap)}")

    for key, value in obj.items():
        emit(key, value)
    return "\n".join(out)
