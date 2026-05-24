"""M7 contract smoke for the Matrix source kind.

One assertion per pinned-from-M0-onward claim. If a future rename or
refactor breaks any of these, this file fails loudly instead of the
breakage silently leaking through the integration tier.
"""

from __future__ import annotations

import pytest

from eyenet.contracts.collector import compute_instance_id
from eyenet.contracts.enums import SourceKind
from eyenet.contracts.identity_pool import _DEVICE_FINGERPRINT_SCHEMAS
from eyenet.contracts.raw_message import subject_for


@pytest.mark.contract
def test_sourcekind_matrix_exists() -> None:
    assert SourceKind.MATRIX.value == "matrix"


@pytest.mark.contract
def test_matrix_device_fingerprint_schema_pinned() -> None:
    schema = _DEVICE_FINGERPRINT_SCHEMAS[SourceKind.MATRIX]
    # Field set per PLAN §6.1. Stored as frozenset; order is irrelevant.
    assert schema == frozenset({"homeserver_url", "device_id", "user_agent"})


@pytest.mark.contract
def test_matrix_subject_template() -> None:
    instance_id = compute_instance_id("alpha_mx", SourceKind.MATRIX)
    subject = subject_for(SourceKind.MATRIX, instance_id)
    assert subject == f"raw.message.matrix.{instance_id}"
    assert len(instance_id) == 8


@pytest.mark.contract
def test_matrix_instance_id_deterministic_across_calls() -> None:
    # Pinned formula: same (identity_name, source_kind) → same instance_id.
    a = compute_instance_id("alpha_mx", SourceKind.MATRIX)
    b = compute_instance_id("alpha_mx", SourceKind.MATRIX)
    assert a == b
    # Cross-source collision-resistance: different SourceKind → different id.
    c = compute_instance_id("alpha_mx", SourceKind.TELEGRAM)
    assert a != c
