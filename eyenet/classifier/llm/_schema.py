"""The wire contract we ASK the model for — and the JSON schema we constrain to.

This pydantic model serves two purposes: (1) :func:`advisory_json_schema`
exports its JSON Schema as Ollama's ``format`` parameter, grammar-constraining
capable models toward valid output; (2) it documents the exact shape the prompt
requests. It is the *contract*, not the *parser* — we never trust a local model
to honor it, so :mod:`._repair` does defensive, lenient coercion regardless of
what the schema promised. The enums here exist to steer the model, not to gate
our parsing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AdvisorySchema", "advisory_json_schema"]


class AdvisorySchema(BaseModel):
    """The structured advisory we request from the model (grammar target)."""

    model_config = ConfigDict(extra="forbid")

    suggested_tier: Literal["normal", "restricted", "classified"] = Field(
        description="Sensitivity tier this document warrants, judged from content alone."
    )
    summary: str = Field(
        description="Neutral 1-3 sentence description of the document and its sensitivity."
    )
    indicators: list[str] = Field(
        default_factory=list,
        description="Short phrases naming the sensitivity signals observed (empty if none).",
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="Confidence in the suggested_tier judgement."
    )


def advisory_json_schema() -> dict[str, object]:
    """The JSON Schema sent to the provider as a structured-output grammar."""
    return AdvisorySchema.model_json_schema()
