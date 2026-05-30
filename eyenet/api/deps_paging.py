# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared cursor-pagination plumbing for v1 read endpoints (M9.F5).

The cursor is an opaque base64url encoding of a non-negative integer offset.
It is deliberately offset-based, not keyset: the read surface is small-operator
scale and the storage list_* methods already speak limit/offset. The opacity
(clients must treat `next_cursor` as a blob) preserves the freedom to switch to
keyset later without a contract change.

`encode_cursor`/`decode_cursor` were first written inline in
`eyenet/api/v1/auth/api_list_tokens.py` (M9.A4); F5 lifts them here so every
paginated endpoint shares one implementation. `CursorParams` bundles the three
shared OpenAPI query params (`cursor`, `limit`, `include_total`) whose component
definitions live in `contracts/openapi/eyenet.v1.yaml#/components/parameters`
(Cursor maxLength 4096, Limit 1..500 default 50, IncludeTotal enum [0,1]).

API_PLAN §8.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from fastapi.exceptions import RequestValidationError


def encode_cursor(offset: int) -> str:
    """Opaque base64url cursor over a non-negative integer offset."""
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def decode_cursor(cursor: str | None) -> int:
    """Decode the opaque cursor to a non-negative offset; 0 when absent.

    A malformed cursor is a client error → 422 (reuses the app's
    RequestValidationError → problem+json handler).
    """
    if cursor is None:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise RequestValidationError(
            [{"loc": ("query", "cursor"), "msg": "malformed cursor", "type": "value_error"}],
        ) from exc
    if offset < 0:
        raise RequestValidationError(
            [{"loc": ("query", "cursor"), "msg": "malformed cursor", "type": "value_error"}],
        )
    return offset


@dataclass(frozen=True)
class CursorParams:
    """Resolved pagination inputs for a read handler.

    `offset` is the already-decoded integer; `limit` is the requested page size;
    `include_total` is whether the client asked for `estimated_total`.
    """

    offset: int
    limit: int
    include_total: bool

    @property
    def fetch_limit(self) -> int:
        """Over-fetch by one to detect a further page without a second query."""
        return self.limit + 1

    def next_cursor(self, *, fetched: int) -> str | None:
        """Next-page cursor given how many rows the over-fetch returned.

        Pass the length of the rows returned by a query that used
        ``fetch_limit``; returns the cursor for the following page, or ``None``
        when this was the last page.
        """
        has_more = fetched > self.limit
        return encode_cursor(self.offset + self.limit) if has_more else None


def cursor_params(
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    include_total: Annotated[int, Query(ge=0, le=1)] = 0,
) -> CursorParams:
    """FastAPI dependency bundling the three shared pagination query params.

    Mirrors the `Cursor` / `Limit` / `IncludeTotal` OpenAPI parameter
    components: cursor (maxLength 4096), limit (1..500, default 50),
    include_total (0/1 integer flag — modeled as a ranged int rather than a
    `Literal` so query-string values coerce cleanly).
    """
    return CursorParams(
        offset=decode_cursor(cursor),
        limit=limit,
        include_total=bool(include_total),
    )


__all__ = ["CursorParams", "cursor_params", "decode_cursor", "encode_cursor"]
