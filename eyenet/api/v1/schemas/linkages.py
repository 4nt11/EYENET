"""Linkage-resource schemas — summary, detail, evidence, decision request.

OpenAPI: `contracts/openapi/eyenet.v1.yaml` — Linkage*, LinkageEvidence,
LinkageDecisionRequest.
API_PLAN §3.2, §3.4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from eyenet.models.linkage import LinkageTable

from ._base import ApiSchema
from .enums import LinkageState
from .pagination import CursorPage


class LinkageSummary(ApiSchema):
    """Projection of MODELS.md §3.2 Linkage for listing surfaces."""

    linkage_id: UUID
    actor_a_id: UUID
    actor_b_id: UUID
    state: LinkageState
    score: float
    method: str = Field(max_length=64)
    proposed_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = Field(
        default=None,
        description=(
            "UUID of the SystemUser who decided. The domain row stores a username "
            "string; the route layer resolves username -> SystemUser.id before "
            "calling `from_domain`."
        ),
    )

    @classmethod
    def from_domain(
        cls,
        linkage: LinkageTable,
        decided_by_user_id: UUID | None = None,
    ) -> LinkageSummary:
        """`decided_by_user_id` is resolved by the route layer via a
        `system_user` lookup keyed on `linkage.decided_by` (username).

        The projector does NOT call storage; passing `None` is valid for
        undecided linkages and for the (rare) case where the username does
        not resolve to a known SystemUser.
        """

        return cls(
            linkage_id=linkage.id,
            actor_a_id=linkage.actor_a_id,
            actor_b_id=linkage.actor_b_id,
            state=linkage.state,
            score=linkage.score,
            method=linkage.method,
            proposed_at=linkage.proposed_at,
            decided_at=linkage.decided_at,
            decided_by=decided_by_user_id,
        )


class LinkageEvidence(ApiSchema):
    """One comparator row from the linkage `evidence` blob."""

    comparator: str = Field(max_length=64)
    score: float
    detail: dict[str, Any] = Field(default_factory=dict)


class LinkageDetail(LinkageSummary):
    """Projection of MODELS.md §3.2 Linkage for `GET /v1/linkages/{id}`.

    Flattens the domain `evidence: dict[str, Any]` into a list of
    `LinkageEvidence` rows — one per top-level comparator key. The dict
    convention is `{comparator_name: {"score": float, **detail}}`.
    """

    evidence: list[LinkageEvidence] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls,
        linkage: LinkageTable,
        decided_by_user_id: UUID | None = None,
    ) -> LinkageDetail:
        evidence_rows: list[LinkageEvidence] = []
        for comparator, payload in (linkage.evidence or {}).items():
            if not isinstance(payload, dict):
                continue
            score = payload.get("score")
            if not isinstance(score, (int, float)):
                continue
            detail = {k: v for k, v in payload.items() if k != "score"}
            evidence_rows.append(
                LinkageEvidence(comparator=comparator, score=float(score), detail=detail),
            )
        return cls(
            linkage_id=linkage.id,
            actor_a_id=linkage.actor_a_id,
            actor_b_id=linkage.actor_b_id,
            state=linkage.state,
            score=linkage.score,
            method=linkage.method,
            proposed_at=linkage.proposed_at,
            decided_at=linkage.decided_at,
            decided_by=decided_by_user_id,
            evidence=evidence_rows,
        )


class LinkageDecisionRequest(ApiSchema):
    """Body for `POST /v1/linkages/{id}/{confirm,reject,suspect}`."""

    reason: str = Field(min_length=1, max_length=1024)
    note: str | None = Field(default=None, max_length=4096)


class CursorPageLinkageSummary(CursorPage[LinkageSummary]):
    """200 page response for `GET /v1/linkages`."""


__all__ = [
    "CursorPageLinkageSummary",
    "LinkageDecisionRequest",
    "LinkageDetail",
    "LinkageEvidence",
    "LinkageSummary",
]
