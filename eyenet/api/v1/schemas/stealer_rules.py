"""Pydantic schemas for the stealer-rules CRUD surface.

The rule body itself is open-ended by design: the DSL has eight matcher
types each with its own match/extract shape, plus optional map/normalize
blocks. We type the ENVELOPE (id/layer/family/priority/path_glob/
requires_container_family/reject_patterns) strictly; the nested
match/extract/map/normalize dicts pass through as ``dict[str, Any]`` and
are validated at WRITE time by ``eyenet.stealer.rules.catalog.rw`` and
at RUN time by the engine's own matchers. That keeps the schema small
and forward-compatible with new matcher types.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StealerRuleIn(BaseModel):
    """Request body for create + replace."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    layer: Literal["container", "content"]
    family: str = Field(min_length=1, max_length=64)
    priority: int
    description: str | None = None
    path_glob: str | None = None
    requires_container_family: str | None = None
    match: dict[str, Any]
    extract: dict[str, Any] | None = None
    map: dict[str, Any] | None = Field(default=None, alias="map")
    reject_patterns: list[str] | None = None
    normalize: list[dict[str, Any]] | None = None


class StealerRuleOut(StealerRuleIn):
    """Response body. Same shape as the input; a separate class so the
    OpenAPI schema stays explicit about response-only additions (none yet,
    but the audit-timestamp fields will land here when the on-disk ledger
    is added)."""


class StealerRuleListOut(BaseModel):
    rules: list[StealerRuleOut]
    total: int
