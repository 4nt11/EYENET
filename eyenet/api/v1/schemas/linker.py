# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linker-maintenance run schemas (anti-spam batch passes triggered from the UI).

OpenAPI: ``contracts/openapi/eyenet.v1.yaml`` — RunInfraResult, DetectCopypastaResult.
"""

from __future__ import annotations

from pydantic import Field

from ._base import ApiSchema


class RunInfraResult(ApiSchema):
    """202 response for POST /v1/linker/run-infra."""

    proposed: int = Field(ge=0, description="shared_infra linkages proposed this run")


class DetectCopypastaResult(ApiSchema):
    """202 response for POST /v1/linker/detect-copypasta."""

    flagged: int = Field(ge=0, description="copypasta templates flagged this run")


__all__ = ["DetectCopypastaResult", "RunInfraResult"]
