"""Document-classifier calibration corpus — labeled samples + findings sidecar.

Slice 9. Pure data layer, mirroring :mod:`eyenet.calibration.corpus` (the Rutify
loader). The document grid (:mod:`eyenet.calibration.document_grid`) is the only
consumer; it replays the deterministic pipeline OFFLINE over these samples.

Two committed files, both JSONL:

* **corpus** — one :class:`DocumentSample` per line: the *extracted text* + the
  *sanitized embedded metadata* a document would yield, plus its operator label
  (``expected_tier``). Synthetic/fictional, so it is safe to commit (real
  operator corpora stay gitignored; the format is identical).
* **findings sidecar** — one row per ``doc_id``: the raw Presidio findings the
  jailed NER worker produced for that sample's text. Presidio is jail-only, so
  the findings are CAPTURED ONCE via the real jail (``eyenet calibrate classify
  capture``) and then replayed offline — keeping the grid + its regression suite
  deterministic and CI-runnable. Regex runs in-process, so it is always live.

The corpus is sha256-pinned: the artifact records the corpus hash, and the
findings must reference only doc_ids present in the corpus (a stale sidecar is a
loud failure, not silent drift).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from eyenet.classifier.presidio._types import PiiFinding
from eyenet.contracts.enums import SensitivityTier

LABEL_VALUES: frozenset[str] = frozenset(t.value for t in SensitivityTier)
"""Valid ``expected_tier`` strings — the three SensitivityTier values."""


@dataclass(frozen=True)
class DocumentSample:
    """One labeled document for tier calibration.

    ``text`` is what the extraction stage would return; ``embedded_meta`` is the
    sanitized embedded metadata (the escalate-only second text source, slice 9).
    ``expected_tier`` is the operator's ground-truth label. ``lang`` is
    informational (the pipeline runs es+en regardless).
    """

    doc_id: str
    expected_tier: SensitivityTier
    text: str
    embedded_meta: dict[str, object] = field(default_factory=dict)
    lang: str | None = None
    notes: str = ""


def sha256_file(path: Path) -> str:
    """Return the sha256 hex of a file's raw bytes (the corpus pin)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_document_samples(path: Path) -> Iterator[DocumentSample]:
    """Stream labeled document samples from the corpus JSONL.

    Loud-fails on malformed JSON, an unknown ``expected_tier``, or a missing
    required field — the corpus is operator-curated, so a parse error is
    corruption, not noise (mirrors the Rutify loader).
    """
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row: dict[str, object] = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"document corpus parse error at line {lineno}: {exc}"
                raise ValueError(msg) from exc

            doc_id = row.get("doc_id")
            text = row.get("text")
            tier_raw = row.get("expected_tier")
            if not isinstance(doc_id, str) or not doc_id:
                msg = f"document corpus line {lineno}: missing/empty 'doc_id'"
                raise ValueError(msg)
            if not isinstance(text, str):
                msg = f"document corpus line {lineno} ({doc_id}): 'text' must be a string"
                raise ValueError(msg)
            if not isinstance(tier_raw, str) or tier_raw not in LABEL_VALUES:
                msg = (
                    f"document corpus line {lineno} ({doc_id}): 'expected_tier' must be "
                    f"one of {sorted(LABEL_VALUES)}, got {tier_raw!r}"
                )
                raise ValueError(msg)

            meta_raw = row.get("embedded_meta")
            embedded_meta = meta_raw if isinstance(meta_raw, dict) else {}
            lang_raw = row.get("lang")
            notes_raw = row.get("notes")
            yield DocumentSample(
                doc_id=doc_id,
                expected_tier=SensitivityTier(tier_raw),
                text=text,
                embedded_meta=embedded_meta,
                lang=lang_raw if isinstance(lang_raw, str) else None,
                notes=notes_raw if isinstance(notes_raw, str) else "",
            )


def load_document_corpus(path: Path) -> list[DocumentSample]:
    """Load the whole corpus into memory, asserting unique doc_ids."""
    samples = list(iter_document_samples(path))
    seen: set[str] = set()
    for s in samples:
        if s.doc_id in seen:
            msg = f"duplicate doc_id in document corpus: {s.doc_id}"
            raise ValueError(msg)
        seen.add(s.doc_id)
    return samples


def load_findings(path: Path) -> dict[str, tuple[PiiFinding, ...]]:
    """Load the captured Presidio findings sidecar → ``{doc_id: (finding, …)}``.

    A doc with no PII has an empty tuple (it must still appear, so a missing
    sidecar row is distinguishable from a no-PII document). Loud-fails on a
    malformed row.
    """
    out: dict[str, tuple[PiiFinding, ...]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                row: dict[str, object] = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"findings sidecar parse error at line {lineno}: {exc}"
                raise ValueError(msg) from exc
            doc_id = row.get("doc_id")
            findings_raw = row.get("findings")
            if not isinstance(doc_id, str) or not doc_id:
                msg = f"findings sidecar line {lineno}: missing/empty 'doc_id'"
                raise ValueError(msg)
            if not isinstance(findings_raw, list):
                msg = f"findings sidecar line {lineno} ({doc_id}): 'findings' must be a list"
                raise ValueError(msg)
            out[doc_id] = tuple(_parse_finding(f, doc_id, lineno) for f in findings_raw)
    return out


def _parse_finding(obj: object, doc_id: str, lineno: int) -> PiiFinding:
    if not isinstance(obj, dict):
        msg = f"findings sidecar line {lineno} ({doc_id}): each finding must be an object"
        raise ValueError(msg)
    try:
        return PiiFinding(
            entity_type=str(obj["entity_type"]),
            start=int(obj["start"]),
            end=int(obj["end"]),
            score=float(obj["score"]),
            language=str(obj["language"]),
            text=str(obj["text"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"findings sidecar line {lineno} ({doc_id}): malformed finding ({exc})"
        raise ValueError(msg) from exc


__all__ = [
    "LABEL_VALUES",
    "DocumentSample",
    "iter_document_samples",
    "load_document_corpus",
    "load_findings",
    "sha256_file",
]
