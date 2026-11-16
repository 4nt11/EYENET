# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for /v1/stealer/audit/* routes (v1.2.7).

Centralises: the FileAuditReader instance, the page/limit Query descriptors,
and the page-meta construction so every audit route returns the same
envelope shape. Keeps each route file short and consistent.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from eyenet.api.v1.schemas.stealer import StealerAuditPageMeta
from eyenet.stealer.query import FileAuditReader

reader = FileAuditReader()

# Pagination contract: page is 1-indexed; limit is one of a fixed list the FE
# exposes as a dropdown so it never sends an unbounded page. The ceiling (100)
# bounds worst-case CH memory use for a single query.
PageParam = Annotated[int, Query(ge=1, description="1-indexed page number.")]
LimitParam = Annotated[
    int,
    Query(ge=1, le=100, description="Rows per page. FE offers 10/25/50/75/100."),
]


def empty_meta(page: int, limit: int) -> StealerAuditPageMeta:
    """Zeroed meta for the uninitialized-corpus response path."""
    return StealerAuditPageMeta(
        page=page, limit=limit, total=0, page_count=0, has_more=False
    )


def built_meta(page: int, limit: int, total: int, page_count: int) -> StealerAuditPageMeta:
    """Pagination envelope with ``has_more`` derived from page vs page_count."""
    return StealerAuditPageMeta(
        page=page,
        limit=limit,
        total=total,
        page_count=page_count,
        has_more=page < page_count,
    )


__all__ = [
    "LimitParam",
    "PageParam",
    "built_meta",
    "empty_meta",
    "reader",
]
