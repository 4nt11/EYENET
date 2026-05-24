"""CLI runtime config — env vars + flag parsing."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def _spanish_disabled_default() -> dict[str, int | None]:
    """Factory for per-language threshold dicts (PLAN §M5 / Rutify 2026-05-22).

    Spanish entries default to ``None`` (disabled). Lives at module scope
    because Pydantic's ``default_factory`` cannot infer the value-type of a
    bare lambda returning ``{"es": None}`` under mypy strict.
    """
    return {"es": None}


def _spanish_pos_ngram_default() -> dict[str, int | None]:
    """M6.5 pos_ngram per-lang default — Spanish DISABLED.

    Rutify calibration (2026-05-23) yielded AUC=0.61 with max precision
    0.20 at any threshold — short Spanish chat doesn't separate within-
    vs cross-author distance distributions well enough. Mirrors the M5
    operator decision on function_word + char_ngram.
    """
    return {"es": None}


def _spanish_optional_grammar_default() -> dict[str, int | None]:
    """M6.5 optional_grammar per-lang default — Spanish DISABLED.

    Rutify calibration (2026-05-23) yielded AUC=0.63 with max precision
    0.08 at any threshold. Same operator decision rationale as the
    sibling M5 + M6.5 simhash disables.
    """
    return {"es": None}


class LinkerThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Language-blind fallbacks (M4 first-principles values). Used when an
    # actor's slot language is not present in the per-lang override dict.
    # Spanish is disabled via the per-lang defaults below.
    function_word_simhash_hamming: int = Field(default=8, ge=0, le=64)
    char_ngram_simhash_hamming: int = Field(default=10, ge=0, le=64)
    # M6.5 spaCy trio (locale-aware). Language-blind defaults; per-lang
    # overrides below decide whether Spanish actually fires the comparator.
    pos_ngram_simhash_hamming: int = Field(default=10, ge=0, le=64)
    optional_grammar_simhash_hamming: int = Field(default=12, ge=0, le=64)

    # Per-language overrides (PLAN §M5). Value semantics:
    #   * int  — use this threshold for actors whose slot language matches.
    #   * None — explicitly DISABLE this comparator for actors of this
    #            language. The Linker skips the comparator entirely (no
    #            VectorIndex upsert, no proposal emission).
    # Disabled-for-language exists because some primitives are empirically
    # uninformative on certain language/domain combinations (e.g. simhash on
    # short Spanish chat — Rutify calibration 2026-05-22). Better to be
    # honest than to ship a calibrated-looking number that is actually noise.
    #
    # Defaults DISABLE both simhash comparators for Spanish, mirroring the
    # committed calibration artifact (rutify_calibration_baseline.json).
    # Operators override per-config to re-enable when a better primitive
    # (minhash-with-shingles in BEHAVE-TEXT 0.0.2) lands.
    function_word_simhash_hamming_per_lang: dict[str, int | None] = Field(
        default_factory=_spanish_disabled_default
    )
    char_ngram_simhash_hamming_per_lang: dict[str, int | None] = Field(
        default_factory=_spanish_disabled_default
    )
    # M6.5 spaCy trio per-language overrides. Default state for Spanish is
    # the language-blind threshold (re-enabled at startup); the M6.5
    # calibration grid against Rutify will flip this to int / None as the
    # data warrants. Until then a calibrated value lives here, NOT a
    # blanket disable — these primitives are designed for Spanish and
    # there is no other language ruleset shipping yet.
    pos_ngram_simhash_hamming_per_lang: dict[str, int | None] = Field(
        default_factory=_spanish_pos_ngram_default
    )
    optional_grammar_simhash_hamming_per_lang: dict[str, int | None] = Field(
        default_factory=_spanish_optional_grammar_default
    )

    def for_comparator(self, name: str, language: str | None = None) -> int | None:
        """Return the configured threshold for a comparator by name.

        Returns:
          int  — the threshold to apply.
          None — comparator is explicitly DISABLED for this language; the
                 Linker MUST skip it.

        When ``language`` is provided and the per-language dict contains the
        language code, the per-language entry wins (including a ``None``
        disable). Otherwise the language-blind default is used.
        """
        if language is not None:
            per_lang_attr = f"{name}_per_lang"
            per_lang = getattr(self, per_lang_attr, None)
            if isinstance(per_lang, dict) and language in per_lang:
                v = per_lang[language]
                return None if v is None else int(v)
        return int(getattr(self, name, 8))


class LinkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: LinkerThresholds = Field(default_factory=LinkerThresholds)


class VerifierThresholds(BaseModel):
    """M8 Verifier per-method score floors.

    Verifier scores live in `[0.0, 1.0]` with higher = more similar — the
    inverse of Linker Hamming distance. A pair becomes SUSPECTED iff the
    composite score (mean of all enabled verifier scores) clears
    ``composite_floor``.

    Per-language overrides mirror the LinkerThresholds shape:
      * float — use this floor for actors whose slot language matches.
      * None  — explicitly DISABLE this verifier for the language.
    """

    model_config = ConfigDict(extra="forbid")

    # Per-verifier minimum score required to count toward the composite.
    general_impostors: float = Field(default=0.60, ge=0.0, le=1.0)
    compression_distance: float = Field(default=0.55, ge=0.0, le=1.0)

    # Per-language overrides. Defaults are empty: the language-blind floor
    # applies until M8 calibration against Rutify decides otherwise.
    general_impostors_per_lang: dict[str, float | None] = Field(default_factory=dict)
    compression_distance_per_lang: dict[str, float | None] = Field(default_factory=dict)

    # Composite score required to promote PROPOSED → SUSPECTED. Mean across
    # all enabled verifier scores. Hand-set floor; the M8 calibration grid
    # will refine it against ground-truth pairs.
    composite_floor: float = Field(default=0.60, ge=0.0, le=1.0)

    # Last-N messages per actor used to assemble the verifier corpus.
    # Bounded so the compressor (NCD) and the impostor sampling (GI) stay
    # predictable on chatty actors.
    window_messages: int = Field(default=500, ge=10, le=10_000)

    def for_verifier(self, name: str, language: str | None = None) -> float | None:
        """Return the configured score floor for a verifier by name.

        Returns:
          float — the score floor to apply.
          None  — verifier is explicitly DISABLED for this language; the
                  VerifierService MUST skip it.

        When ``language`` is provided and the per-language dict contains the
        language code, the per-language entry wins (including a ``None``
        disable). Otherwise the language-blind default is used.
        """
        if language is not None:
            per_lang_attr = f"{name}_per_lang"
            per_lang = getattr(self, per_lang_attr, None)
            if isinstance(per_lang, dict) and language in per_lang:
                v = per_lang[language]
                return None if v is None else float(v)
        return float(getattr(self, name, 0.5))


class VerifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: VerifierThresholds = Field(default_factory=VerifierThresholds)


class RuntimeConfig(BaseModel):
    """Resolved runtime config for an EYENET service process."""

    model_config = ConfigDict(extra="forbid")

    nats_url: str = Field(default="nats://127.0.0.1:4222")
    data_dir: Path
    identities_path: Path | None = None
    otlp_endpoint: str | None = None
    use_memory_bus: bool = False  # tests / dev-loop convenience
    linker: LinkerConfig = Field(default_factory=LinkerConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)

    @classmethod
    def from_env(
        cls,
        *,
        data_dir: Path | None = None,
        identities_path: Path | None = None,
        nats_url: str | None = None,
        use_memory_bus: bool | None = None,
    ) -> RuntimeConfig:
        return cls(
            nats_url=nats_url or os.environ.get("EYENET_NATS_URL", "nats://127.0.0.1:4222"),
            data_dir=data_dir or Path(os.environ.get("EYENET_DATA_DIR", "./data")),
            identities_path=identities_path or _opt_path(os.environ.get("EYENET_IDENTITIES")),
            otlp_endpoint=os.environ.get("EYENET_OTLP_ENDPOINT") or None,
            use_memory_bus=use_memory_bus
            if use_memory_bus is not None
            else os.environ.get("EYENET_MEMORY_BUS", "0") == "1",
        )


def _opt_path(s: str | None) -> Path | None:
    return Path(s) if s else None


__all__ = [
    "LinkerConfig",
    "LinkerThresholds",
    "RuntimeConfig",
    "VerifierConfig",
    "VerifierThresholds",
]
