"""Operator labels — TOML schema, loader, validator.

Labels feed recipe calibration (Phase 4). Each label records:

* ``sender_id`` — pseudonymous Telegram integer; the only identifier we
  keep at this layer (no usernames; those live in the gitignored corpus).
* ``label`` — one of ``LABEL_VALUES``: ``lurker``, ``bot``,
  ``chatty_member``, ``normal``, ``unknown``.
* ``confidence`` — ``high`` / ``medium`` / ``low``. Recipe search can
  filter or weight by this.
* ``notes`` — free-text justification. Auditable; not used by code.

The file as a whole records corpus provenance:

* ``corpus_id`` (string), ``corpus_sha256`` (the JSONL's sha256),
* ``labeled_at`` (ISO date),
* ``labeler`` (identifier — when Claude is the labeler this is
  ``"claude-opus-4-7-via-anti"``; PLAN locked the policy on 2026-05-22).

A file with no actor entries is valid (no recipe calibration possible).
A file with mismatched ``corpus_sha256`` is a HARD ERROR — operator must
re-label or pin to the right corpus.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

LABEL_VALUES: frozenset[str] = frozenset({"lurker", "bot", "chatty_member", "normal", "unknown"})
CONFIDENCE_VALUES: frozenset[str] = frozenset({"high", "medium", "low"})


@dataclass(frozen=True)
class ActorLabel:
    """One labeled actor."""

    sender_id: int
    label: str
    confidence: str
    notes: str

    def __post_init__(self) -> None:
        if self.label not in LABEL_VALUES:
            msg = (
                f"invalid label {self.label!r} for sender {self.sender_id}; "
                f"must be one of {sorted(LABEL_VALUES)}"
            )
            raise ValueError(msg)
        if self.confidence not in CONFIDENCE_VALUES:
            msg = (
                f"invalid confidence {self.confidence!r} for sender {self.sender_id}; "
                f"must be one of {sorted(CONFIDENCE_VALUES)}"
            )
            raise ValueError(msg)


@dataclass(frozen=True)
class LabelSet:
    """Loaded labels file + provenance."""

    corpus_id: str
    corpus_sha256: str
    labeled_at: str
    labeler: str
    actors: tuple[ActorLabel, ...]

    @property
    def by_sender(self) -> dict[int, ActorLabel]:
        return {a.sender_id: a for a in self.actors}

    def counts(self) -> dict[str, int]:
        """Label → count of actors carrying it. Useful for sanity reports."""
        out: dict[str, int] = dict.fromkeys(LABEL_VALUES, 0)
        for a in self.actors:
            out[a.label] += 1
        return out


def load(path: Path) -> LabelSet:
    """Load and validate the labels TOML.

    Raises :class:`ValueError` on missing required keys or unknown enum
    values. The corpus sha256 is NOT validated against an actual corpus
    file here — call :func:`assert_matches_corpus` after load when you
    have the corpus path.
    """
    raw_bytes = path.read_bytes()
    data = tomllib.loads(raw_bytes.decode("utf-8"))

    required = {"corpus_id", "corpus_sha256", "labeled_at", "labeler"}
    missing = required - set(data.keys())
    if missing:
        msg = f"labels file {path} missing required keys: {sorted(missing)}"
        raise ValueError(msg)

    raw_actors = data.get("actor", [])
    if not isinstance(raw_actors, list):
        msg = f"labels file {path}: [[actor]] must be an array of tables"
        raise ValueError(msg)

    actors: list[ActorLabel] = []
    for i, row in enumerate(raw_actors):
        if not isinstance(row, dict):
            msg = f"labels file {path}: actor #{i} is not a table"
            raise ValueError(msg)
        sender_id = row.get("sender_id")
        if not isinstance(sender_id, int):
            msg = f"labels file {path}: actor #{i} missing/invalid sender_id"
            raise ValueError(msg)
        actors.append(
            ActorLabel(
                sender_id=sender_id,
                label=str(row.get("label", "")),
                confidence=str(row.get("confidence", "")),
                notes=str(row.get("notes", "")),
            )
        )

    seen: set[int] = set()
    for a in actors:
        if a.sender_id in seen:
            msg = f"labels file {path}: duplicate sender_id {a.sender_id}"
            raise ValueError(msg)
        seen.add(a.sender_id)

    return LabelSet(
        corpus_id=str(data["corpus_id"]),
        corpus_sha256=str(data["corpus_sha256"]),
        labeled_at=str(data["labeled_at"]),
        labeler=str(data["labeler"]),
        actors=tuple(actors),
    )


def assert_matches_corpus(labels: LabelSet, corpus_sha256: str) -> None:
    """Hard-fail when the labels file targets a different corpus.

    Recipe calibration MUST refuse to combine labels from corpus A with
    feature stats from corpus B — they are not interchangeable.
    """
    if labels.corpus_sha256 != corpus_sha256:
        msg = (
            f"labels corpus mismatch: file targets {labels.corpus_sha256[:12]}…, "
            f"actual corpus is {corpus_sha256[:12]}…"
        )
        raise ValueError(msg)


__all__ = [
    "CONFIDENCE_VALUES",
    "LABEL_VALUES",
    "ActorLabel",
    "LabelSet",
    "assert_matches_corpus",
    "load",
]
