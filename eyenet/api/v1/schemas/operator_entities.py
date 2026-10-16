# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request/response schemas for operator-asserted entity creation (canvas).

Hand-created actors / groups / artifacts for the exploration canvas. Each create
returns a compact ``OperatorEntityCreated`` — the canvas already holds the labels
the operator typed, so it just needs the new ``id`` to place the node.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from eyenet.contracts.enums import GroupKind

from ._base import ApiSchema

# Same open-kind form the indicator ruleset / API validates elsewhere.
_ARTIFACT_KIND = r"^[a-z][a-z0-9_]{1,63}$"


class CreateOperatorActorRequest(ApiSchema):
    """Body of ``POST /v1/actors``. At least one of handle/display_name required
    (a node with no label is useless)."""

    handle: str | None = Field(default=None, min_length=1, max_length=512)
    display_name: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _need_a_label(self) -> CreateOperatorActorRequest:
        if self.handle is None and self.display_name is None:
            raise ValueError("at least one of handle or display_name is required")
        return self


class CreateOperatorGroupRequest(ApiSchema):
    """Body of ``POST /v1/groups``. The operator picks ``kind`` from the existing
    GroupKind set; provenance marks it operator-asserted."""

    title: str | None = Field(default=None, min_length=1, max_length=512)
    kind: GroupKind


class CreateOperatorArtifactRequest(ApiSchema):
    """Body of ``POST /v1/artifacts``. ``kind`` is an open slug (vendored
    InfrastructureKind or operator-custom); ``value`` is deduped by hash."""

    kind: str = Field(pattern=_ARTIFACT_KIND, description="open kind slug")
    value: str = Field(min_length=1, max_length=2048)


class CreatePersonaRequest(ApiSchema):
    """Body of ``POST /v1/personas/standalone``: a persona from operator analysis
    (not a merge), labelled, with no members yet."""

    label: str = Field(min_length=1, max_length=512)


class OperatorEntityCreated(ApiSchema):
    """201 body for every operator-entity create."""

    id: UUID
    entity_type: str
