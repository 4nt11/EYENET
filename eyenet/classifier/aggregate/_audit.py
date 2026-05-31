"""Pure builder for the ``eyenet.audit.classify.*`` payload.

Provenance is itself evidence (CLASSIFIER_PLAN §4): the audit row must let an
operator reproduce and defend the tier. This serializes a
:class:`ClassificationVerdict` into JSON-safe primitives — REDACTED, so no raw
matched span ever lands in the (non-clearance-gated) audit log. The emit itself
(subject_id / evidence_ref / publisher) is wired by the ClassifierService in a
later slice; this module only shapes the payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._types import ClassificationVerdict

__all__ = ["classification_audit_payload"]


def classification_audit_payload(verdict: ClassificationVerdict) -> dict[str, object]:
    """Serialize a verdict into the redacted, JSON-safe audit payload."""
    redacted = verdict.redacted()
    payload: dict[str, object] = {
        "tier": verdict.tier.value,
        "fail_closed": verdict.fail_closed,
        "consult_llm": verdict.consult_llm,
        "ruleset_version": verdict.regex.ruleset_version,
        "pii_map_version": verdict.presidio.map_version,
        "provenance": [
            {
                "stage": p.stage,
                "tier_floor": p.tier_floor.value,
                "version": p.version,
                "fail_closed": p.fail_closed,
                "detail": p.detail,
            }
            for p in verdict.provenance
        ],
        "regex_matches": [
            {
                "rule": m.rule_name,
                "tier_floor": m.tier_floor.value,
                "start": m.start,
                "end": m.end,
                "lang": m.lang,
                "matched_text": m.matched_text,  # masked via verdict.redacted()
            }
            for m in redacted.regex.matches
        ],
        "presidio_matches": [
            {
                "entity_type": m.entity_type,
                "tier_floor": m.tier_floor.value,
                "start": m.start,
                "end": m.end,
                "score": m.score,
                "language": m.language,
                "matched_text": m.matched_text,  # masked via verdict.redacted()
            }
            for m in redacted.presidio.matches
        ],
        "review_flags": [
            {
                "kind": f.kind.value,
                "detail": f.detail,
                "suggested_tier": (
                    f.suggested_tier.value if f.suggested_tier is not None else None
                ),
                "corroborated": f.corroborated,
            }
            for f in verdict.review_flags
        ],
    }
    if verdict.llm is not None:
        # Safe metadata ONLY — the LLM's summary/indicators paraphrase document
        # content and may quote sensitive spans, so they NEVER reach the
        # (non-clearance-gated) audit log.
        payload["llm"] = {
            "suggested_tier": verdict.llm.suggested_tier.value,
            "confidence": verdict.llm.confidence,
            "model": verdict.llm.model,
            "attempts": verdict.llm.attempts,
            "truncated_input": verdict.llm.truncated_input,
        }
    return payload
