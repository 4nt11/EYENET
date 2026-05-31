"""Load + validate the PII-type → tier map (operator-editable TOML).

Mirrors :mod:`eyenet.classifier.ruleset._loader`: a strict pydantic shape
(``extra="forbid"``) and eager, fail-closed validation. A silently-dropped
mapping here becomes *under-classification* downstream, which is the one
unrecoverable failure mode (CLASSIFIER_PLAN §0), so any malformed map refuses to
load whole — we never half-apply one.

Unlike the ruleset there is no regex to compile; the "compile" step is shape +
range validation and parking disabled entities. ``min_score`` is constrained to
[0, 1] and the density thresholds must be ordered (``restricted_at`` ≤
``classified_at``) — an inverted pair would make a higher tier need *fewer*
findings than a lower one.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eyenet.contracts.enums import SensitivityTier

from ._types import EntityRule, PiiMap

__all__ = ["PII_MAP_ENV", "load_pii_map"]

_log = structlog.get_logger()

PII_MAP_ENV = "EYENET_CLASSIFIER_PII_MAP"
_BUNDLED_DEFAULT = Path(__file__).parent / "_default_pii_map.toml"


class EntitySpec(BaseModel):
    """One operator-authored PII-type mapping."""

    model_config = ConfigDict(extra="forbid")

    name: str  # presidio entity label, e.g. "US_SSN", "PERSON"
    tier_floor: SensitivityTier
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    description: str = ""
    # A disabled entity is parked: kept in the file for calibration but not loaded
    # into the map, so it never contributes a floor or a density count. Used for
    # the noisiest NER types (DATE_TIME / URL) that fire on near-every document
    # and would collapse the density signal into noise — same discipline as the
    # ruleset's parked shape rules. Their real home is slice-9 calibration.
    enabled: bool = True


class DensitySpec(BaseModel):
    """Distinct-PII-count thresholds that escalate the floor by clustering."""

    model_config = ConfigDict(extra="forbid")

    restricted_at: int = Field(gt=0)  # >= this many distinct PII spans -> RESTRICTED
    classified_at: int = Field(gt=0)  # >= this many -> CLASSIFIED

    @model_validator(mode="after")
    def _ordered(self) -> DensitySpec:
        if self.classified_at < self.restricted_at:
            raise ValueError(
                "density classified_at must be >= restricted_at "
                f"(got {self.classified_at} < {self.restricted_at})"
            )
        return self


class PiiMapFile(BaseModel):
    """Parsed shape of a PII-map TOML file."""

    model_config = ConfigDict(extra="forbid")

    map_version: str
    density: DensitySpec
    entities: list[EntitySpec]


def _resolve_path(path: Path | None) -> Path:
    """Explicit arg wins; else the env override; else the bundled default."""
    if path is not None:
        return path
    env = os.environ.get(PII_MAP_ENV)
    if env:
        return Path(env)
    return _BUNDLED_DEFAULT


def load_pii_map(path: Path | None = None) -> PiiMap:
    """Load and validate a PII map.

    ``path=None`` loads the operator override (``EYENET_CLASSIFIER_PII_MAP``) if
    set, otherwise the bundled default. Raises :class:`FileNotFoundError` if the
    file is absent and :class:`ValueError` on any shape/range/duplicate error.
    """
    resolved = _resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"classifier PII map not found: {resolved}")

    parsed = PiiMapFile.model_validate(tomllib.loads(resolved.read_text("utf-8")))

    entities: dict[str, EntityRule] = {}
    seen: set[str] = set()
    disabled = 0
    for spec in parsed.entities:
        if spec.name in seen:
            raise ValueError(f"duplicate PII entity: {spec.name!r}")
        seen.add(spec.name)
        if not spec.enabled:
            disabled += 1
            continue
        entities[spec.name] = EntityRule(tier_floor=spec.tier_floor, min_score=spec.min_score)

    _log.info(
        "classify.pii_map_loaded",
        map_version=parsed.map_version,
        n_entities=len(entities),
        n_disabled=disabled,
        restricted_at=parsed.density.restricted_at,
        classified_at=parsed.density.classified_at,
        source=str(resolved),
    )
    return PiiMap(
        map_version=parsed.map_version,
        entities=entities,
        restricted_at=parsed.density.restricted_at,
        classified_at=parsed.density.classified_at,
    )
