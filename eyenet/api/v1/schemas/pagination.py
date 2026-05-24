"""Cursor pagination wrapper.

`CursorPage[T]` is generic for handler ergonomics. Concrete typed aliases
(`CursorPagePATSummary`, `CursorPageLinkageSummary`, ...) live alongside
their item schemas so FastAPI generates the same flat schema names that
the hand-drafted OpenAPI uses.

OpenAPI: `contracts/openapi/eyenet.v1.yaml#/components/schemas/CursorPageBase`
API_PLAN §8.
"""

from __future__ import annotations

from pydantic import Field

from ._base import ApiSchema


class CursorPage[T](ApiSchema):
    """Opaque-cursor page of `T`. `estimated_total` only when `?include_total=1`."""

    items: list[T] = Field(description="Page items, ordered per endpoint's documented sort.")
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for the next page; null when this is the last page.",
    )
    estimated_total: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Best-effort filtered count, capped at 10000. Present only when the "
            "client requested ?include_total=1. Use for UI hints, never for control flow."
        ),
    )


__all__ = ["CursorPage"]
