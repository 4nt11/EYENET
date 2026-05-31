"""In-jail Presidio PII detector. Runs ONLY inside nsjail, in the extract venv.

Reads /input (the already-extracted document text, UTF-8), NFC-normalizes it,
and runs Microsoft Presidio NER over it in BOTH Spanish and English, then emits
the {"text", "meta"} envelope the chokepoint expects, with the PII findings in
``meta["findings"]``. The pure mapper in the main app turns those findings into a
tier floor — this worker only DETECTS, it never decides a tier.

Spanish-first (es is EYENET's calibrated language) but English is run too: a
multilingual threat-actor corpus analyzed with only the es engine would
under-detect English names, and under-classification is the one catastrophic
error (CLASSIFIER_PLAN §0). Both passes are unioned; the mapper dedups overlaps.

Third-party imports (presidio_analyzer, spacy models) live only in the
eyenet-extract venv, so this module is excluded from the app's lint/type/dep
checks. It is bind-mounted and run as a script, never imported by the app.
Single-threadedness is forced by the profile's env (OMP_THREAD_LIMIT=1, ...), so
thinc/numpy never attempt clone3 thread creation under the no-spawn allowlist.
"""

import json
import sys
import unicodedata

# Presidio's EmailRecognizer validates an email's TLD with the MODULE-GLOBAL
# tldextract extractor, whose default REFRESHES the public-suffix list over HTTP.
# In the jail the snapshot cache is read-only and there is no network, so the
# fetch does a DNS lookup (getaddrinfo) that — with no /etc in the chroot — makes
# glibc spawn a resolver thread (clone3), which the no-spawn seccomp policy KILLs
# (slice-2 doctrine: clone3 is unfilterable) -> SIGSYS -> the whole pass fails
# closed. Replace the global extractor with an OFFLINE one before importing
# presidio: empty suffix_list_urls disables the network entirely, cache_dir=None
# avoids the read-only cache write, and the bundled snapshot still resolves TLDs —
# so email/URL detection keeps working with zero network and zero threads.
import tldextract

tldextract.extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

import presidio_analyzer  # noqa: E402  (must follow the tldextract override above)
from presidio_analyzer import AnalyzerEngine  # noqa: E402
from presidio_analyzer.nlp_engine import NlpEngineProvider  # noqa: E402

_LANGS = ("es", "en")
_NLP_CONFIG = {
    "nlp_engine_name": "spacy",
    "models": [
        {"lang_code": "es", "model_name": "es_core_news_sm"},
        {"lang_code": "en", "model_name": "en_core_web_sm"},
    ],
}


def _build_analyzer() -> AnalyzerEngine:
    engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIG).create_engine()
    return AnalyzerEngine(nlp_engine=engine, supported_languages=list(_LANGS))


def _analyzer_version() -> str:
    # presidio_analyzer is imported at module top, so this never raises; the
    # default only covers a build that ships no __version__ attribute.
    return str(getattr(presidio_analyzer, "__version__", "unknown"))


def main() -> int:
    with open("/input", "rb") as handle:
        raw = handle.read()
    text = unicodedata.normalize("NFC", raw.decode("utf-8", "replace"))

    analyzer = _build_analyzer()
    findings = []
    for lang in _LANGS:
        for r in analyzer.analyze(text=text, language=lang):
            findings.append(
                {
                    "entity_type": r.entity_type,
                    "start": r.start,
                    "end": r.end,
                    "score": float(r.score),
                    "language": lang,
                    "text": text[r.start : r.end],
                }
            )

    envelope = {
        "text": "",
        "meta": {
            "findings": findings,
            "analyzer": _analyzer_version(),
            "languages": list(_LANGS),
        },
    }
    sys.stdout.write(json.dumps(envelope))
    return 0


if __name__ == "__main__":
    sys.exit(main())
