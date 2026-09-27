# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export operator label corrections as gold training data.

Closes the retraining loop: every operator relabel (incident_label rows) is written as
one JSONL line in the shape dataset/train_mmbert_ml.py already consumes as GOLD human
truth — ``{"text": <message body>, "labels": [<corrected heads>]}``. Naming the output
``*.mllabels.jsonl`` means the trainer's ``load_gold()`` glob picks it up with no code
change: gold-train folds in as human-truth overrides, gold-test gives honest per-head
numbers. An empty ``labels`` is a real negative (operator said "false positive").

Extra keys (message_id, reason, decided_by) are provenance; the trainer keys on text and
ignores them.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, cast

from eyenet.telemetry import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from eyenet.contracts.incident import IncidentLabelRow
    from eyenet.storage.repository import BaseRepository

_log = get_logger()


def _write(out_path: Path, lines: list[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


async def export_operator_labels(storage: BaseRepository, out_path: Path) -> int:
    """Write every operator correction to ``out_path`` as gold JSONL. Returns row count.

    Corrections whose message body is no longer retained are skipped (no text to train on)."""
    rows = cast("list[IncidentLabelRow]", await storage.all_incident_labels())
    bodies = await storage.bodies_by_message_ids([r.message_id for r in rows])

    written = 0
    lines: list[str] = []
    for r in rows:
        text = bodies.get(r.message_id)
        if text is None:
            continue
        lines.append(
            json.dumps(
                {
                    "text": text,
                    "labels": r.labels,  # [] = false positive (a true negative example)
                    "message_id": str(r.message_id),
                    "reason": r.reason,
                    "decided_by": r.decided_by,
                },
                ensure_ascii=False,
            )
        )
        written += 1

    await asyncio.to_thread(_write, out_path, lines)  # blocking IO off the event loop
    _log.info("incident.export_labels", written=written, out=str(out_path))
    return written
