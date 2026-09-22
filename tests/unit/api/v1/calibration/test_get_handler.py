# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call unit test for GET /v1/calibration (calibration_get)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.calibration.api_get_calibration import calibration_get

pytestmark = pytest.mark.unit


async def test_calibration_reports_baseline(mkuser: Callable[..., CurrentUser]) -> None:
    view = await calibration_get(mkuser("read:actors"))
    assert 0.0 <= view.composite_floor <= 1.0
    names = {c.name for c in view.comparators}
    assert "function_word_simhash_hamming" in names
    assert len(view.comparators) == 4
    # Spanish is DISABLED for both simhash comparators (Rutify baseline).
    fw = next(c for c in view.comparators if c.name == "function_word_simhash_hamming")
    assert fw.per_lang.get("es") is None
    assert {v.name for v in view.verifiers} == {"general_impostors", "compression_distance"}
