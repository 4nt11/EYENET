"""EYENET Verifier tier (M8).

Sibling to the Linker (`eyenet/linker/`). Where the Linker proposes
pairwise linkages from cheap signature-distance metrics, the Verifier
operates on raw per-actor corpora -- fills the gap M5 calibration opened
for Spanish (all four simhashes disabled, AUC ceiling 0.55-0.68).

Bus shape:
    in  : attribution.linkage.proposed   (Linker output)
    out : attribution.linkage.suspected  (when composite clears threshold)

State machine: PROPOSED → SUSPECTED (existing transition, see
`eyenet.storage.linkages.SQLiteLinkageStore.transition`). The Verifier
service is the only autonomous source of the SUSPECTED state — operator
CLI can still issue `eyenet linkage suspect` for triage.
"""

from __future__ import annotations

from .service import VerifierService
from .verifiers import REGISTRY, default_registry

__all__ = ["REGISTRY", "VerifierService", "default_registry"]
