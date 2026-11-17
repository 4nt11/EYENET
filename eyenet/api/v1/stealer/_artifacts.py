# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for /v1/stealer/artifacts/* routes (v1.3.3)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from eyenet.api.v1.schemas.stealer import StealerAuditPageMeta
from eyenet.stealer.query import StealerArtifactsReader

reader = StealerArtifactsReader()

PageParam = Annotated[int, Query(ge=1, description="1-indexed page number.")]
LimitParam = Annotated[
    int,
    Query(ge=1, le=100, description="Rows per page. FE offers 10/25/50/75/100."),
]


def built_meta(page: int, limit: int, total: int, page_count: int) -> StealerAuditPageMeta:
    return StealerAuditPageMeta(
        page=page,
        limit=limit,
        total=total,
        page_count=page_count,
        has_more=page < page_count,
    )


def empty_meta(page: int, limit: int) -> StealerAuditPageMeta:
    return StealerAuditPageMeta(
        page=page, limit=limit, total=0, page_count=0, has_more=False
    )


__all__ = ["LimitParam", "PageParam", "built_meta", "empty_meta", "reader"]
