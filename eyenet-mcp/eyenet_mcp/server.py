# SPDX-License-Identifier: AGPL-3.0-or-later
"""The MCP server: two read tools (search, get) over /v1, PAT forwarded.

Config via env:
  EYENET_MCP_BASE   base URL of the API (default http://localhost:8000)
  EYENET_MCP_TOKEN  an existing PAT; forwarded as Bearer. Carries the clearance
                    tier — a thin result is redaction, not a bug.

Writes are out of scope here by design (development/MCP_PLAN.md §4a). This stays
a read lens until the graph phase.
"""

from __future__ import annotations

import os

import httpx
from mcp.server.mcpserver import MCPServer  # mcp 2.x (was FastMCP in 1.x)

from .render import offset_to_cursor, parse_handle, record_text, render_search, resource_for

mcp = MCPServer("eyenet")


def _verify() -> bool | str:
    """EYENET_MCP_VERIFY: 0/false → skip TLS verify (self-signed localhost),
    a path → use that CA bundle, anything else → verify (default)."""
    v = os.environ.get("EYENET_MCP_VERIFY", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "yes", "on", ""):
        return True
    return os.environ["EYENET_MCP_VERIFY"]  # treat as CA bundle path


def _client() -> httpx.AsyncClient:
    base = os.environ.get("EYENET_MCP_BASE", "https://localhost:8443").rstrip("/")
    token = os.environ.get("EYENET_MCP_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(base_url=base, headers=headers, timeout=30.0, verify=_verify())


async def _get_json(path: str, params: dict[str, str | int] | None = None) -> dict | str:
    """GET and return parsed JSON, or a legible `error: …` string. The MCP
    framework swallows raised exceptions into an opaque failure, so surface the
    cause as text instead — the model needs to see *why* a call failed."""
    base = os.environ.get("EYENET_MCP_BASE", "https://localhost:8443")
    try:
        async with _client() as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"error: HTTP {exc.response.status_code} — {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"error: cannot reach API at {base}: {type(exc).__name__}: {exc}"


@mcp.tool()
async def search(kind: str, q: str, count: int = 20, offset: int = 0) -> str:
    """Search the EYENET corpus; the front door for almost every task.

    kind: one entity type to search (actor, persona, artifact, message, thread,
          incident, indicator, linkage, …). `kind="all"` searches every type.
    q:    the query string (required). ponytail: empty-q browse is the next
          increment and needs per-resource list endpoints — not wired yet.
    count/offset: page size and start; the reply ends with `next:<cursor>` when
          more exist — pass it back as `offset` is for synthesized offsets, or
          re-call with a larger offset.

    Returns terse hit lines `kind:id  title — snippet`. Open one with `get`.
    Clearance comes from the token; a thin result is redaction — do not retry.
    """
    params: dict[str, str | int] = {"q": q, "limit": count}
    if kind and kind != "all":
        params["types"] = kind
    cursor = offset_to_cursor(offset)
    if cursor:
        params["cursor"] = cursor
    page = await _get_json("/v1/search", params)
    return page if isinstance(page, str) else render_search(page)


@mcp.tool()
async def get(handle: str, full: bool = False, evidence: bool = False) -> str:
    """Open one record by its `kind:id` handle (from a search hit).

    Three tiers, cheapest first — use the least that answers the question:
    - default: each field snippeted.
    - full=true: the sanitized fields in full (e.g. a message's plaintext `body`).
    - evidence=true: additionally unlock the RAW evidence fields (`body_html`,
      `source_specific`). You rarely need this — the sanitized body is the readable
      one; the raw HTML is forensic fidelity, not for reading.

    Every value is capped regardless, so a leak-dump field can't blow the budget.
    """
    kind, ident = parse_handle(handle)
    obj = await _get_json(f"/v1/{resource_for(kind)}/{ident}")
    return obj if isinstance(obj, str) else record_text(kind, obj, full=full, evidence=evidence)


def main() -> None:
    """stdio entry point (the `eyenet-mcp` console script)."""
    mcp.run("stdio")


if __name__ == "__main__":
    main()
