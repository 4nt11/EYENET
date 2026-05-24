"""General Impostors (GI) verifier — Koppel/Schler.

For each random feature subsample (function-word distribution OR char-
trigram distribution), compute cosine similarity between actor A and B and
between A and each of K impostor pool actors. Score = fraction of
``n_iters`` iterations in which B's similarity to A strictly exceeds every
impostor's similarity to A — the classic "could a stranger fool us?"
ratio.

Calibration: the threshold floor lives in
``eyenet.cli.config.VerifierThresholds.general_impostors``. M5's Rutify
corpus serves as the impostor pool — committed to
``tests/fixtures/calibration/impostor_pool.jsonl`` once the M8 calibration
grid is run. Until then a synthetic seed pool keeps the verifier
deterministic during development.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from ._bag import (
    char_trigram_vector,
    cosine,
    function_word_vector,
)
from ._base import VerificationResult


class GeneralImpostors:
    name: str = "general_impostors"
    version: str = "0.1"
    requires_language: bool = False
    min_messages_per_actor: int = 30

    def __init__(
        self,
        impostor_corpora: Sequence[list[str]] | None = None,
        *,
        n_iters: int = 100,
        seed: int = 20260523,
    ) -> None:
        """impostor_corpora: list of per-impostor message lists.

        n_iters: number of bootstrap iterations. Each iteration randomly
        samples a feature subspace (function words OR char trigrams) and
        evaluates the "is B closer than every impostor?" test.

        seed: random seed. Calibration MUST hold this constant so AUC and
        F1 sweeps are reproducible across runs.
        """
        self._impostors: list[list[str]] = (
            [list(c) for c in impostor_corpora] if impostor_corpora is not None else []
        )
        self._n_iters = n_iters
        self._seed = seed

    @property
    def impostor_count(self) -> int:
        return len(self._impostors)

    def verify(
        self,
        corpus_a: list[str],
        corpus_b: list[str],
        *,
        language: str | None,
    ) -> VerificationResult:
        if (
            len(corpus_a) < self.min_messages_per_actor
            or len(corpus_b) < self.min_messages_per_actor
        ):
            return VerificationResult(
                method=self.name,
                score=0.0,
                confidence=0.0,
                skipped=True,
                skip_reason="corpus_too_short",
                evidence={
                    "min_messages": self.min_messages_per_actor,
                    "len_a": len(corpus_a),
                    "len_b": len(corpus_b),
                },
            )
        if not self._impostors:
            # No impostor pool → degenerate but still safe: degrade to
            # plain cosine similarity, mark low confidence so the
            # composite weights it down.
            sim = self._plain_cosine(corpus_a, corpus_b, language=language)
            return VerificationResult(
                method=self.name,
                score=sim,
                confidence=0.3,
                skipped=False,
                skip_reason=None,
                evidence={"impostor_count": 0, "degraded_to": "plain_cosine"},
            )

        rng = random.Random(self._seed)  # noqa: S311  # nosec B311 — bootstrap sampling, not crypto
        wins = 0
        for _ in range(self._n_iters):
            feature_kind = rng.choice(("function_word", "char_trigram"))
            # Bootstrap each side by sampling half the messages (with replacement)
            sub_a = self._subsample(corpus_a, rng)
            sub_b = self._subsample(corpus_b, rng)
            sim_ab = self._sim(sub_a, sub_b, language=language, kind=feature_kind)
            impostor_max = 0.0
            for imp in self._impostors:
                if not imp:
                    continue
                sub_imp = self._subsample(imp, rng)
                sim_ai = self._sim(sub_a, sub_imp, language=language, kind=feature_kind)
                impostor_max = max(impostor_max, sim_ai)
            if sim_ab > impostor_max:
                wins += 1
        score = wins / self._n_iters
        return VerificationResult(
            method=self.name,
            score=score,
            confidence=1.0,
            skipped=False,
            skip_reason=None,
            evidence={
                "impostor_count": len(self._impostors),
                "n_iters": self._n_iters,
                "wins": wins,
            },
        )

    @staticmethod
    def _subsample(corpus: list[str], rng: random.Random) -> list[str]:
        k = max(1, len(corpus) // 2)
        return [rng.choice(corpus) for _ in range(k)]

    def _sim(
        self,
        a: list[str],
        b: list[str],
        *,
        language: str | None,
        kind: str,
    ) -> float:
        if kind == "function_word":
            return cosine(
                function_word_vector(a, language=language),
                function_word_vector(b, language=language),
            )
        return cosine(char_trigram_vector(a), char_trigram_vector(b))

    def _plain_cosine(
        self,
        a: list[str],
        b: list[str],
        *,
        language: str | None,
    ) -> float:
        fw = cosine(
            function_word_vector(a, language=language),
            function_word_vector(b, language=language),
        )
        ct = cosine(char_trigram_vector(a), char_trigram_vector(b))
        return (fw + ct) / 2.0


__all__ = ["GeneralImpostors"]
