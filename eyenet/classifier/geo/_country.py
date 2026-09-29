"""Victim-country attribution from breach-dump text/metadata — deterministic, no ML.

The question this answers: *whose data is in this dump?* (the victim jurisdiction),
not *who dumped it* (the actor). Actor geo is a different problem.

**A multi-check engine.** Several independent checks each emit weighted, per-country
signals; they are combined into ONE score per country. A poster-authored title label
is weighted heavily (it is operator-grade ground truth), but body PII still
contributes — it corroborates the title and decides on its own when the title names
no country. Add a new check by adding an extractor and a weight; nothing else
changes.

Checks:

* **Title country name / alias / demonym** — from a ``pycountry``-derived gazetteer.
* **Title ccTLD** — a ccTLD is essentially the ISO 3166 alpha-2, so
  ``pycountry.countries.get(alpha_2=tld.upper())`` resolves ``.cl``→CL, ``.com.br``
  →BR, ``.gov.co``→CO with no separate TLD table.
* **Body national ID** — checksummed (CL RUT, mod-11, and it must carry the ``-``
  before the check digit: a *bare* run of digits is any country's ID and passes
  mod-11 ~9% of the time, which produced the Argentine/Peru false positives).
* **Body IBAN** — mod-97. **Body phone** — country code via libphonenumber.

Combining: each (country, check) group contributes ``weight * min(count, cap)`` so
evidence KIND dominates evidence COUNT (200 accidental RUTs can't out-vote a
"Russia" title). The leader resolves only if it clears an absolute floor AND holds
the majority share; else unknown (too weak) or mixed (split). Never force a single
origin onto a genuinely multi-national dump.

Pure and I/O-free. Regex candidates use google-re2 (linear-time, ReDoS-immune)
because dump text is attacker-authored.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import cycle
from typing import TYPE_CHECKING, Any

import phonenumbers
import pycountry
import re2
import structlog

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ["ENGINE_VERSION", "CountrySignal", "CountryVerdict", "classify_country"]

# Bump when the checks, weights, or gates change — lets the store detect stale
# verdicts and recompute (parallels the incident model_version).
ENGINE_VERSION = "geo-1"

_log = structlog.get_logger()

# Per-check weights for the combined multi-check engine. Every check feeds ONE
# score per country; a title label is authoritative (heavy) but body PII still
# contributes and corroborates. Tuned so an explicit country name outweighs any
# amount of saturated body evidence — that is what stops a dump full of foreign
# national IDs from out-voting its own "Russia"/"Peru" title.
_WEIGHTS: dict[str, float] = {
    "country_name": 100.0,  # explicit country name/alias/demonym in the title
    "cctld": 40.0,  # ccTLD of a domain named in the title
    "national_id": 20.0,  # checksummed national ID in the body (CL RUT, ...)
    "iban": 20.0,
    "phone": 10.0,
}
_W_NAME = _WEIGHTS["country_name"]
_W_CCTLD = _WEIGHTS["cctld"]
_W_IBAN = _WEIGHTS["iban"]
_W_NATIONAL_ID = _WEIGHTS["national_id"]
_W_PHONE = _WEIGHTS["phone"]

# Repeated hits of the SAME check for the SAME country saturate: the Nth identical
# RUT adds nothing past the cap, so evidence COUNT can't dominate evidence KIND.
_SATURATE_CAP = 3
# The leader must hold this share of total score to be a single origin (else mixed)
# and reach this absolute floor to resolve at all (else too weak -> unknown).
_MAJORITY = 0.6
_MIN_SCORE = 10.0

# RUT mod-11 maps a remainder of 10 to the check char 'K' (0 stays '0').
_RUT_K_REMAINDER = 10

_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False

# --- Title gazetteer (built once from pycountry) --------------------------------

# Short forms / spellings pycountry's canonical names miss.
_ALIASES: dict[str, str] = {
    "russia": "RU",
    "brasil": "BR",
    "turkey": "TR",
    "turkiye": "TR",
    "türkiye": "TR",
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "uk": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "great britain": "GB",
    "south korea": "KR",
    "north korea": "KP",
    "uae": "AE",
    "ivory coast": "CI",
    "iran": "IR",
    "syria": "SY",
    "venezuela": "VE",
    "bolivia": "BO",
    "tanzania": "TZ",
    "moldova": "MD",
    "vietnam": "VN",
    "laos": "LA",
    "czech republic": "CZ",
}

# Demonyms seen in real dump titles ("Turkish ISP", "Argentine …", "Somali …").
_DEMONYMS: dict[str, str] = {
    "chilean": "CL",
    "argentine": "AR",
    "argentinian": "AR",
    "peruvian": "PE",
    "brazilian": "BR",
    "colombian": "CO",
    "venezuelan": "VE",
    "uruguayan": "UY",
    "paraguayan": "PY",
    "mexican": "MX",
    "turkish": "TR",
    "italian": "IT",
    "somali": "SO",
    "indonesian": "ID",
    "russian": "RU",
    "hungarian": "HU",
    "dominican": "DO",
    "spanish": "ES",
    "french": "FR",
    "german": "DE",
    "polish": "PL",
    "bulgarian": "BG",
    "ugandan": "UG",
    "saudi": "SA",
    "lithuanian": "LT",
    "moroccan": "MA",
    "tunisian": "TN",
    "indian": "IN",
    "british": "GB",
    "chinese": "CN",
    "japanese": "JP",
    "korean": "KR",
}


def _build_name_gazetteer() -> tuple[dict[str, str], Any]:  # Any: re2 pattern has no stubs
    """Lowercase name/alias/demonym -> ISO alpha-2, plus a compiled alternation."""
    table: dict[str, str] = {}
    for country in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            value = getattr(country, attr, None)
            if value:
                table[value.lower()] = country.alpha_2
    table.update(_ALIASES)
    table.update(_DEMONYMS)
    # Longest-first so multi-word names anchor before any substring of them.
    alternation = "|".join(re2.escape(k) for k in sorted(table, key=len, reverse=True))
    pattern = re2.compile(rf"(?i)\b(?:{alternation})\b", _RE2_OPTIONS)
    return table, pattern


_NAME_TO_ISO, _NAME_RE = _build_name_gazetteer()

# ccTLDs commonly (ab)used as generic/tech TLDs — don't infer a country from these.
_CCTLD_STOPLIST = frozenset({"IO", "AI", "ME", "TV", "CC", "FM", "GG", "TO", "WS", "LY"})
# ccTLDs that are NOT the ISO alpha-2 of their country.
_CCTLD_EXCEPTIONS = {"uk": "GB"}
_CCTLD_LEN = 2  # a ccTLD is a two-letter code
_DOMAIN_RE = re2.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", _RE2_OPTIONS)

# --- Body signals ---------------------------------------------------------------

_IBAN_RE = re2.compile(r"\b[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}\b", _RE2_OPTIONS)
# RUT: 7-8 body digits (optionally dotted) + MANDATORY '-' + check digit (0-9/K).
# The dash is what separates a real RUT from a bare foreign national-ID number.
_RUT_RE = re2.compile(r"\b([0-9]{1,2})\.?([0-9]{3})\.?([0-9]{3})-([0-9Kk])\b", _RE2_OPTIONS)


def _tail(span: str, keep: int = 4) -> str:
    """Mask a captured span for the verdict/logs — keep the last few chars."""
    if len(span) <= keep:
        return "*" * len(span)
    return "*" * min(len(span) - keep, 8) + span[-keep:]


def _iban_ok(candidate: str) -> bool:
    """ISO 13616 mod-97: move the first 4 chars to the end, A=10..Z=35, %97==1."""
    rearranged = candidate[4:] + candidate[:4]
    total = 0
    for ch in rearranged:
        total = total * 100 + (ord(ch) - 55) if ch.isalpha() else total * 10 + int(ch)
    return total % 97 == 1


def _rut_check_digit(body: str) -> str:
    """Chilean RUT mod-11: weight body digits right-to-left by 2..7 (repeating)."""
    total = sum(int(ch) * f for ch, f in zip(reversed(body), cycle((2, 3, 4, 5, 6, 7))))
    remainder = (11 - total % 11) % 11  # 0..10; 0 stays '0', 10 -> 'K'
    return "K" if remainder == _RUT_K_REMAINDER else str(remainder)


def _name_signals(title: str) -> Iterable[tuple[str, str]]:
    """Yield (ISO, evidence) for every country name/alias/demonym in the title."""
    for m in _NAME_RE.finditer(title):
        matched = m.group(0)
        iso = _NAME_TO_ISO.get(matched.lower())
        if iso:
            yield iso, matched


def _cctld_signals(title: str) -> Iterable[tuple[str, str]]:
    """Yield (ISO, evidence) for the ccTLD of every domain named in the title."""
    for m in _DOMAIN_RE.finditer(title):
        tld = m.group(0).rsplit(".", 1)[-1].lower()
        if tld in _CCTLD_EXCEPTIONS:
            yield _CCTLD_EXCEPTIONS[tld], m.group(0)
            continue
        if len(tld) != _CCTLD_LEN or not tld.isalpha() or tld.upper() in _CCTLD_STOPLIST:
            continue
        country = pycountry.countries.get(alpha_2=tld.upper())
        if country:
            yield country.alpha_2, m.group(0)


def _phone_signals(text: str) -> Iterable[tuple[str, str]]:
    """Yield (ISO region, evidence) for every VALID phone number found."""
    for match in phonenumbers.PhoneNumberMatcher(text, None):
        region = phonenumbers.region_code_for_number(match.number)
        if region and region != "ZZ":
            yield region, _tail(match.raw_string)


def _iban_signals(text: str) -> Iterable[tuple[str, str]]:
    """Yield (ISO country, evidence) for every checksum-valid IBAN."""
    for m in _IBAN_RE.finditer(text):
        candidate = m.group(0)
        if _iban_ok(candidate):
            yield candidate[:2], _tail(candidate)


def _rut_signals(text: str) -> Iterable[tuple[str, str]]:
    """Yield ('CL', evidence) for every checksum-valid Chilean RUT (dash required)."""
    for m in _RUT_RE.finditer(text):
        body = m.group(1) + m.group(2) + m.group(3)
        if _rut_check_digit(body) == m.group(4).upper():
            yield "CL", _tail(m.group(0))


# Override registry: ISO country -> extractor for that country's checksummed
# national ID. Base-layer countries need no entry.
_NATIONAL_ID: dict[str, Callable[[str], Iterable[tuple[str, str]]]] = {
    "CL": _rut_signals,
}


@dataclass(frozen=True, slots=True)
class CountrySignal:
    """One geo signal firing: the country it points at, how, and masked evidence."""

    iso: str  # ISO 3166-1 alpha-2
    kind: str  # "country_name" | "cctld" | "national_id" | "iban" | "phone"
    weight: float
    evidence: str


@dataclass(frozen=True, slots=True)
class CountryVerdict:
    """Victim-country verdict for one document.

    ``country`` is the resolved ISO alpha-2, or ``None`` when the evidence is
    absent (``status="unknown"``, includes too-weak) or split
    (``status="mixed"``). ``decided_by`` is the check kind that contributed most to
    the winner (e.g. "country_name", "national_id"), or None. ``distribution`` is
    the combined per-country score, descending; ``signals`` carries every signal
    found for provenance.
    """

    country: str | None
    status: str  # "resolved" | "mixed" | "unknown"
    decided_by: str | None
    distribution: tuple[tuple[str, float], ...]
    signals: tuple[CountrySignal, ...]


def _all_checks(text: str, title: str) -> list[CountrySignal]:
    """Run every check and return the pooled signals (title + body, one list)."""
    signals: list[CountrySignal] = []
    for iso, ev in _name_signals(title):
        signals.append(CountrySignal(iso=iso, kind="country_name", weight=_W_NAME, evidence=ev))
    for iso, ev in _cctld_signals(title):
        signals.append(CountrySignal(iso=iso, kind="cctld", weight=_W_CCTLD, evidence=ev))
    for extractor in _NATIONAL_ID.values():
        for iso, ev in extractor(text):
            signals.append(
                CountrySignal(iso=iso, kind="national_id", weight=_W_NATIONAL_ID, evidence=ev)
            )
    for iso, ev in _iban_signals(text):
        signals.append(CountrySignal(iso=iso, kind="iban", weight=_W_IBAN, evidence=ev))
    for iso, ev in _phone_signals(text):
        signals.append(CountrySignal(iso=iso, kind="phone", weight=_W_PHONE, evidence=ev))
    return signals


def _combine(
    signals: list[CountrySignal],
) -> tuple[str | None, str, str | None, tuple[tuple[str, float], ...]]:
    """Combine all checks into one score per country, then apply the gates.

    Each (country, check-kind) group contributes its weight times the saturated hit
    count, so evidence KIND dominates evidence COUNT. The leader resolves only if it
    reaches the absolute floor AND holds the majority share; otherwise unknown/mixed.
    """
    grouped: Counter[tuple[str, str]] = Counter((s.iso, s.kind) for s in signals)
    score: dict[str, float] = {}
    best_kind: dict[str, tuple[float, str]] = {}
    for (iso, kind), n in grouped.items():
        contribution = _WEIGHTS[kind] * min(n, _SATURATE_CAP)
        score[iso] = score.get(iso, 0.0) + contribution
        if contribution > best_kind.get(iso, (0.0, ""))[0]:
            best_kind[iso] = (contribution, kind)

    ranked = tuple(sorted(score.items(), key=lambda kv: (-kv[1], kv[0])))
    if not ranked:
        return None, "unknown", None, ranked
    top_iso, top_score = ranked[0]
    total = sum(score.values())
    if top_score < _MIN_SCORE:
        return None, "unknown", None, ranked  # some evidence, but too weak to attribute
    if top_score / total < _MAJORITY:
        return None, "mixed", None, ranked
    return top_iso, "resolved", best_kind[top_iso][1], ranked


def classify_country(text: str, *, title: str | None = None) -> CountryVerdict:
    """Attribute the victim country of a breach dump with a multi-check engine.

    Every check (title country name, title ccTLD, body national ID, IBAN, phone)
    contributes to one combined per-country score. A title label is weighted heavily
    enough to be authoritative, but body PII still corroborates and decides when the
    title is silent. Text is NFC-normalized so composed/decomposed forms match.
    """
    title_norm = unicodedata.normalize("NFC", title) if title else ""
    body_norm = unicodedata.normalize("NFC", text)

    signals = _all_checks(body_norm, title_norm)
    country, status, decided_by, distribution = _combine(signals)

    _log.info(
        "classify.geo_country",
        country=country,
        status=status,
        decided_by=decided_by,
        distribution=[iso for iso, _ in distribution[:5]],
    )
    return CountryVerdict(
        country=country,
        status=status,
        decided_by=decided_by,
        distribution=distribution,
        signals=tuple(signals),
    )
