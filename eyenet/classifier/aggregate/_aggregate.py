"""The aggregator: bind the three deterministic floors into one tier (§4).

Pure and I/O-free — no nsjail, no DB, no network, no LLM call. Re-running it on
the same three stage outputs MUST yield the same verdict; that reproducibility
is the defensibility argument ("the tier was set by deterministic rules only").

The tier is a monotone ``MAX`` and is NEVER lowered (CLASSIFIER_PLAN §0): an
extraction that failed closed or a Presidio pass that failed closed forces
CLASSIFIED. Counter-signals (the ruleset's ``normal``-floor false-positive
rules) and — later — the advisory LLM can only raise an ``operator_review``
flag; the demotion they suggest is a human decision, never automatic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from eyenet.classifier.ruleset._types import max_tier
from eyenet.classifier.sandbox import FailedClosed
from eyenet.contracts.enums import SensitivityTier

from ._types import ClassificationVerdict, ReviewFlag, ReviewKind, StageProvenance

if TYPE_CHECKING:
    from eyenet.classifier.presidio._types import PresidioVerdict
    from eyenet.classifier.ruleset._types import RegexVerdict
    from eyenet.classifier.sandbox import ExtractResult

__all__ = ["aggregate"]

_log = structlog.get_logger()

# Ruleset counter-signal rules (tier_floor = normal): NEGATIVE evidence that a
# higher-tier match may be a false positive. They never lower the tier; their
# co-occurrence with an FP-prone marking raises a review flag instead.
_COUNTER_SIGNAL_RULES = frozenset({"fp_template_placeholder", "fp_creative_works"})

# Markings the ruleset descriptions flag as FP-prone calibration targets — a tier
# these (and ONLY these) drove is a demotion CANDIDATE when a counter-signal
# co-occurs. UNCALIBRATED starting set; slice 9 tunes it against the corpus.
_FP_PRONE_RULES = frozenset(
    {
        "banner_en",  # CONFIDENTIAL bleeds into email footers
        "banner_un",  # STRICTLY CONFIDENTIAL overlaps NDA boilerplate
        "corp_confidential_en",  # INTERNAL USE ONLY — default template footer
        "corp_confidential_es",  # USO INTERNO
        "corp_confidential_pt",
        "caveats_uk_en",  # OFFICIAL-SENSITIVE on routine HMG mail
        "caveats_au_ca_en",  # PROTECTED adjective use
    }
)


def _extraction_provenance(extraction: ExtractResult | FailedClosed) -> StageProvenance:
    """Map the extraction outcome to its stage floor (§0 fail-closed = CLASSIFIED).

    A :class:`FailedClosed` outcome forces CLASSIFIED; a successful
    :class:`ExtractResult` floors at NORMAL. An empty-but-successful extraction
    is the EXTRACTION layer's trusted call (slice 2 returns ``FailedClosed`` if
    it could not read) — the aggregator does not second-guess it.
    """
    if isinstance(extraction, FailedClosed):
        return StageProvenance(
            stage="extraction",
            tier_floor=SensitivityTier.CLASSIFIED,
            version=extraction.reason.value,
            fail_closed=True,
            detail=extraction.detail,
        )
    method = str(extraction.meta.get("doc_kind", "unknown"))
    empty = bool(extraction.meta.get("empty"))
    ocr = bool(extraction.meta.get("ocr_applied"))
    return StageProvenance(
        stage="extraction",
        tier_floor=SensitivityTier.NORMAL,
        version=method,
        detail=f"empty={empty} ocr={ocr}",
    )


def _counter_signal_flags(
    *,
    tier: SensitivityTier,
    regex: RegexVerdict,
    presidio: PresidioVerdict,
    fail_closed: bool,
) -> tuple[ReviewFlag, ...]:
    """Raise a possible-over-classification flag, but NEVER lower the tier (§0).

    Fires only when a counter-signal co-occurs with an FP-prone marking that
    ALONE drove the tier: nothing failed closed, the tier is above NORMAL,
    Presidio did not independently reach the tier (a PII-driven tier is not a
    false positive), and every tier-driving regex rule is in the FP-prone set.
    """
    if fail_closed or tier is SensitivityTier.NORMAL:
        return ()
    counter = sorted({m.rule_name for m in regex.matches if m.rule_name in _COUNTER_SIGNAL_RULES})
    if not counter:
        return ()
    if presidio.tier_floor == tier:  # PII drove the tier — not a false positive
        return ()
    tier_driving = [m for m in regex.matches if m.tier_floor == tier]
    if not tier_driving or not all(m.rule_name in _FP_PRONE_RULES for m in tier_driving):
        return ()
    drivers = sorted({m.rule_name for m in tier_driving})
    detail = (
        f"counter-signal {counter} co-occurs with FP-prone tier driver(s) {drivers}; "
        "operator review may demote — tier left unchanged (§0)"
    )
    return (
        ReviewFlag(
            kind=ReviewKind.POSSIBLE_OVER_CLASSIFICATION,
            detail=detail,
            suggested_tier=SensitivityTier.NORMAL,
        ),
    )


def aggregate(
    extraction: ExtractResult | FailedClosed,
    regex: RegexVerdict,
    presidio: PresidioVerdict,
) -> ClassificationVerdict:
    """Bind the three deterministic floors into one tier + provenance (§4).

    ``tier = MAX(extraction_floor, regex_floor, presidio_floor)`` — monotone and
    never lowered. A failed-closed extraction or Presidio pass forces CLASSIFIED.
    Counter-signal co-occurrence raises a review flag but leaves the tier intact.
    Deterministic: the same three inputs yield an identical verdict.
    """
    extraction_prov = _extraction_provenance(extraction)
    regex_prov = StageProvenance(
        stage="regex",
        tier_floor=regex.tier_floor,
        version=regex.ruleset_version,
    )
    presidio_prov = StageProvenance(
        stage="presidio",
        tier_floor=presidio.tier_floor,
        version=presidio.map_version,
        fail_closed=presidio.fail_closed,
    )

    tier = max_tier((extraction_prov.tier_floor, regex.tier_floor, presidio.tier_floor))
    fail_closed = extraction_prov.fail_closed or presidio.fail_closed

    review_flags = _counter_signal_flags(
        tier=tier, regex=regex, presidio=presidio, fail_closed=fail_closed
    )
    consult_llm = tier is not SensitivityTier.CLASSIFIED and not fail_closed

    # Operational log — floors/counts/versions only, NEVER the raw matched spans
    # (logs are not clearance-gated; slice-3/4 convention).
    _log.info(
        "classify.aggregate",
        tier=tier.value,
        extraction_floor=extraction_prov.tier_floor.value,
        regex_floor=regex.tier_floor.value,
        presidio_floor=presidio.tier_floor.value,
        fail_closed=fail_closed,
        consult_llm=consult_llm,
        n_flags=len(review_flags),
        flags=[f.kind.value for f in review_flags],
    )
    return ClassificationVerdict(
        tier=tier,
        provenance=(extraction_prov, regex_prov, presidio_prov),
        regex=regex,
        presidio=presidio,
        review_flags=review_flags,
        consult_llm=consult_llm,
        fail_closed=fail_closed,
    )
