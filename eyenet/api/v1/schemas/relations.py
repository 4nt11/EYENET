# SPDX-License-Identifier: AGPL-3.0-or-later
"""Relation-builder run schema (actor-to-actor mention/forward batch pass).

OpenAPI: ``contracts/openapi/eyenet.v1.yaml`` — RebuildRelationsResult.
"""

from __future__ import annotations

from pydantic import Field

from ._base import ApiSchema


class RebuildRelationsResult(ApiSchema):
    """202 response for POST /v1/relations/rebuild."""

    edges: int = Field(ge=0, description="actor-to-actor relation edges materialized")


__all__ = ["RebuildRelationsResult"]
