"""EYENET Document Classifier (M10).

Assigns the authoritative ``classifier_tier`` (``SensitivityTier``) to incoming
binary evidence at reception — attachments and standalone operator uploads.

The pipeline is **fail-closed**: anything that cannot be read, parsed, or
confidently classified defaults to the highest tier pending operator review.
The tier decision is 100% deterministic (``MAX`` of regex + PII floors); the
local LLM is a flag-only tripwire that never mutates the tier.

The first and load-bearing component is the extraction **sandbox** — hostile
documents are parsed only inside an nsjail cage whose containment is re-proven
on every boot. See :mod:`eyenet.classifier.sandbox`.
"""

from __future__ import annotations
