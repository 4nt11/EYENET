"""EYENET contracts — bus envelopes, DB row schemas, ABC interfaces.

PLAN §4.1: `/contracts/` is the schema directory. `Surface=db` modules MUST
NOT export a `SUBJECT`; `Surface=bus` / `bus+db` modules export exactly one.
The build-gate test (`tests/unit/contracts/test_surface_gate.py`) refuses
the build if this is violated.
"""

from __future__ import annotations

from ._base import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_MAJOR,
    SCHEMA_VERSION_MINOR,
    BusEnvelope,
    DbRowBase,
    TraceContext,
    canonical_json,
)

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_VERSION_MAJOR",
    "SCHEMA_VERSION_MINOR",
    "BusEnvelope",
    "DbRowBase",
    "TraceContext",
    "canonical_json",
]
