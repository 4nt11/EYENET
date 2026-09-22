# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calibration read schemas — the linker comparator + verifier tuning posture.

Projects the shipped calibration baseline (`LinkerThresholds` /
`VerifierThresholds`) so the BEHAVE readout can render which comparators are
enabled/disabled per language and the verifier composite floor. A `null`
per-language threshold means the comparator/verifier is DISABLED for that
language (e.g. simhash on short Spanish chat — Rutify calibration).
"""

from __future__ import annotations

from pydantic import Field

from ._base import ApiSchema


class ComparatorCalibration(ApiSchema):
    """One linker simhash comparator's language-blind default + per-language map."""

    name: str = Field(max_length=64)
    language_blind_threshold: int = Field(ge=0, le=64)
    per_lang: dict[str, int | None] = Field(default_factory=dict)


class VerifierCalibration(ApiSchema):
    """One verifier's language-blind score floor + per-language map."""

    name: str = Field(max_length=64)
    language_blind_floor: float = Field(ge=0.0, le=1.0)
    per_lang: dict[str, float | None] = Field(default_factory=dict)


class CalibrationView(ApiSchema):
    """200 response for `GET /v1/calibration` — the shipped tuning baseline."""

    composite_floor: float = Field(ge=0.0, le=1.0)
    comparators: list[ComparatorCalibration] = Field(default_factory=list)
    verifiers: list[VerifierCalibration] = Field(default_factory=list)


__all__ = ["CalibrationView", "ComparatorCalibration", "VerifierCalibration"]
