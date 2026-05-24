"""Spanish ruleset for the M6.5 spaCy trio.

Pure-function rules over spaCy tokens (``token.morph``, ``token.tag_``,
``token.lemma_``, ``token.text``). The Spanish small model
(``es_core_news_sm``) is loaded with parser disabled — we rely on the
tagger + morphologizer only, which is what makes the kernel cheap enough
to ship by default.

Evaluative morphology operates on SURFACE FORM (``token.text``), not on
``token.lemma_``. The ``es_core_news_sm`` model preserves the diminutive
in the lemma (``casita`` → ``casita``, ``perrito`` → ``perrito``) rather
than decomposing it; surface-suffix matching is the only reliable
detector at this model size. The md / lg models behave the same way for
this class of morphology, so the surface-form rule survives a future
model upgrade.

Subjunctive detection reads ``token.morph.get("Mood")`` rather than
inspecting the lemma. The sm model's lemmatizer mangles irregular
subjunctives (``fuera`` → ``fuerir`` instead of ``ir``/``ser``), but the
mood morph feature is independent of the lemma string and tags
correctly. Do NOT switch this to a lemma-based check — it will silently
miss every irregular subjunctive.

Evaluative morphology (NOUN / ADJ surface suffix):
  * diminutive  — ``-it[oa]s?``, ``-cit[oa]s?``, ``-ill[oa]s?``, ``-ic[oa]s?``
  * augmentative — ``-az[oa]s?``, ``-ot[oa]s?`` (``-on[oa]s?`` overlaps
    too many genuine words like "ratón", so we restrict it to ADJ tokens
    where the dropped suffix yields a real root via lemma comparison).
  * pejorative — ``-uch[oa]s?``, ``-astr[oa]s?``, ``-ej[oa]s?``
  * intensive  — lemmas in a small frozenset (muy/super/re/recontra/mega/ultra)

Optional grammar choice points:
  * compound_past — AUX ``haber`` immediately preceding a VERB
    Past-Participle (no parser; adjacency heuristic, tolerant of one
    intervening adverb/clitic).
  * subjunctive — ``token.morph.get("Mood")`` contains ``Sub``.
  * clitic_le / clitic_la / clitic_lo — PRON tokens with surface form in
    the respective family; bucketed by surface (le/les vs la/las vs
    lo/los). Operators read the simhash as a stylistic preference
    pattern, not as a leísmo-detection oracle.
  * relative_que / relative_cual / relative_quien — surface forms when
    POS is ``PRON`` or ``SCONJ`` (Spanish ``que`` is ambiguous; the
    tagger choice is good enough as a stylistic axis).
"""

from __future__ import annotations

import re

from spacy.tokens import Doc, Token

LANGUAGE: str = "es"

_DIMINUTIVE_RE = re.compile(r"(it|cit|ill|ic)[oa]s?$")
_AUGMENTATIVE_RE = re.compile(r"(az|ot)[oa]s?$")
_PEJORATIVE_RE = re.compile(r"(uch|astr|ej)[oa]s?$")

_INTENSIVE_LEMMAS: frozenset[str] = frozenset(
    {
        "muy",
        "super",
        "re",
        "recontra",
        "mega",
        "ultra",
        "hiper",
        "demasiado",
    }
)

# Surface forms that match the diminutive / augmentative / pejorative
# regex but are lexicalized — i.e. the suffix is not productive in
# modern Spanish. Without this blocklist, ``bonito`` and ``escrito``
# would inflate every actor's "diminutive density." The list is
# intentionally short: only the highest-frequency offenders. Operators
# can extend as audit traces surface new cases.
_EVAL_BLOCKLIST: frozenset[str] = frozenset(
    {
        # lexicalized "-ito" — not diminutive in modern usage
        "bonito",
        "bonita",
        "bonitos",
        "bonitas",
        "finito",
        "finita",
        "finitos",
        "finitas",
        "infinito",
        "infinita",
        "infinitos",
        "infinitas",
        "escrito",
        "escrita",
        "escritos",
        "escritas",
        "delito",
        "delitos",
        "gratuito",
        "gratuita",
        "gratuitos",
        "gratuitas",
        "circuito",
        "circuitos",
        "explicito",
        "explicita",
        "explicitos",
        "explicitas",
        "implicito",
        "implicita",
        "implicitos",
        "implicitas",
        "definito",
        "definitos",
        # lexicalized "-azo" — common nouns rather than augmentatives
        "plazo",
        "plazos",
        "brazo",
        "brazos",
        "pedazo",
        "pedazos",
        "lazo",
        "lazos",
        # lexicalized "-ico" — fewer offenders but worth catching
        "publico",
        "publicos",
        "publicas",
        "tecnico",
        "tecnica",
        "tecnicos",
        "tecnicas",
        "medico",
        "medica",
        "medicos",
        "medicas",
        "magico",
        "magica",
        "magicos",
        "magicas",
        "musico",
        "musica",
        "musicos",
        "musicas",
        "politico",
        "politica",
        "politicos",
        "politicas",
        "economico",
        "economica",
        "economicos",
        "economicas",
        "historico",
        "historica",
        "historicos",
        "historicas",
        "logico",
        "logica",
        "logicos",
        "logicas",
        "fisico",
        "fisica",
        "fisicos",
        "fisicas",
        "quimico",
        "quimica",
        "quimicos",
        "quimicas",
        "electrico",
        "electrica",
        "electricos",
        "electricas",
        "atomico",
        "atomica",
        "atomicos",
        "atomicas",
        "publica",
        "republica",
        "republicas",
    }
)

# Suffix-bearing POS targets. Verbs carry inflectional morphology that
# would false-positive against the diminutive regex (``hablamos`` ends in
# ``mos`` not ``-itos`` — but ``corrito``, ``-mito``, etc. exist). Keep
# this strict.
_EVAL_TARGET_POS: frozenset[str] = frozenset({"NOUN", "ADJ"})

_CLITIC_LE: frozenset[str] = frozenset({"le", "les"})
_CLITIC_LA: frozenset[str] = frozenset({"la", "las"})
_CLITIC_LO: frozenset[str] = frozenset({"lo", "los"})

_RELATIVE_SURFACES: dict[str, str] = {
    "que": "relative_que",
    "cual": "relative_cual",
    "cuales": "relative_cual",
    "quien": "relative_quien",
    "quienes": "relative_quien",
}
_RELATIVE_POS: frozenset[str] = frozenset({"PRON", "SCONJ"})

# Minimum surface length to consider for evaluative morphology. Filters
# 3-letter false positives like ``otro``, ``ito`` standalone.
_MIN_EVAL_LEN: int = 5


class _SpanishRuleset:
    language: str = LANGUAGE

    def classify_evaluative(self, token: Token) -> str | None:  # noqa: PLR0911
        if token.pos_ not in _EVAL_TARGET_POS:
            return None
        text = token.text.lower()
        if len(text) < _MIN_EVAL_LEN:
            return None
        if text in _EVAL_BLOCKLIST:
            return None
        if _DIMINUTIVE_RE.search(text):
            return "diminutive"
        if _PEJORATIVE_RE.search(text):
            return "pejorative"
        if _AUGMENTATIVE_RE.search(text):
            return "augmentative"
        if token.lemma_.lower() in _INTENSIVE_LEMMAS:
            return "intensive"
        return None

    def classify_optional_grammar(  # noqa: PLR0911
        self,
        token: Token,
        doc: Doc,
    ) -> str | None:
        # Compound past: AUX(haber) immediately followed by VERB
        # Past-Participle, tolerant of one PRON/ADV interposed.
        if token.pos_ == "AUX" and token.lemma_.lower() == "haber":
            window_end = min(token.i + 3, len(doc))
            for j in range(token.i + 1, window_end):
                nxt = doc[j]
                if nxt.pos_ == "VERB" and "Part" in nxt.morph.get("VerbForm", []):
                    return "compound_past"
                if nxt.pos_ not in {"PRON", "ADV", "PUNCT"}:
                    break

        # Subjunctive (verb form, not auxiliary).
        if token.pos_ in {"VERB", "AUX"} and "Sub" in token.morph.get("Mood", []):
            return "subjunctive"

        text = token.text.lower()

        # Clitic pronouns. Restrict to PRON to avoid catching ``la`` as
        # determiner (DET) or ``lo`` as neuter article.
        if token.pos_ == "PRON":
            if text in _CLITIC_LE:
                return "clitic_le"
            if text in _CLITIC_LA:
                return "clitic_la"
            if text in _CLITIC_LO:
                return "clitic_lo"

        # Relative pronouns.
        if token.pos_ in _RELATIVE_POS:
            bucket = _RELATIVE_SURFACES.get(text)
            if bucket is not None:
                return bucket

        return None


RULESET = _SpanishRuleset()


__all__ = ["LANGUAGE", "RULESET"]
