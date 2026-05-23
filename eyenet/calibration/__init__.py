"""EYENET calibration package.

Grid-search runner for linker comparator thresholds and recipe operating
points against a labeled corpus. Produces a hash-pinned ``CalibrationArtifact``
that the calibration test suite asserts against.

Public API is intentionally thin:

- :func:`corpus.iter_messages` / :func:`corpus.group_by_sender` — JSONL ingest.
- :func:`simhash_grid.run` — within/cross Hamming + AUC + F1 sweep.
- :func:`interaction.compute_actor_stats` — per-actor behavioural stats.
- :func:`recipes_grid.run` — recipe threshold search vs labels.
- :class:`artifact.CalibrationArtifact` — hash-pinned output document.

This module is operator-side tooling: it imports from
:mod:`eyenet.sensor.primitives` directly (no NATS round trip) and from
:mod:`behave_text.spec` for primitive types.

See ``PLAN.md`` §M5 and the M5 plan file at
``~/.claude/plans/quiet-wondering-eich.md`` for design rationale.
"""

from __future__ import annotations
