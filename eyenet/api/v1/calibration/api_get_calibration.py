# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/calibration — the shipped linker/verifier tuning baseline.

Reflects the committed `LinkerThresholds` / `VerifierThresholds` defaults (the
same values the calibration artifact ships). Per-service operator overrides are
process-local and not exposed here. Read-gated with read:actors (dossier
context — the BEHAVE readout renders comparator enabled/disabled state).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.calibration import (
    CalibrationView,
    ComparatorCalibration,
    VerifierCalibration,
)
from eyenet.cli.config import LinkerThresholds, VerifierThresholds

router = APIRouter(tags=["calibration"])

# The four linker simhash comparators, in reporting order.
_COMPARATORS = (
    "function_word_simhash_hamming",
    "char_ngram_simhash_hamming",
    "pos_ngram_simhash_hamming",
    "optional_grammar_simhash_hamming",
)
_VERIFIERS = ("general_impostors", "compression_distance")


@router.get(
    "/calibration",
    operation_id="calibration_get",
    response_model=CalibrationView,
    status_code=200,
)
async def calibration_get(
    _: Annotated[CurrentUser, Depends(RequireScope("read:actors"))],
) -> CalibrationView:
    linker = LinkerThresholds()
    verifier = VerifierThresholds()
    comparators = [
        ComparatorCalibration(
            name=name,
            language_blind_threshold=getattr(linker, name),
            per_lang=dict(getattr(linker, f"{name}_per_lang")),
        )
        for name in _COMPARATORS
    ]
    verifiers = [
        VerifierCalibration(
            name=name,
            language_blind_floor=getattr(verifier, name),
            per_lang=dict(getattr(verifier, f"{name}_per_lang")),
        )
        for name in _VERIFIERS
    ]
    return CalibrationView(
        composite_floor=verifier.composite_floor,
        comparators=comparators,
        verifiers=verifiers,
    )
