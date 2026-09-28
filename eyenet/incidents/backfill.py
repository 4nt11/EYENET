# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backfill incident classification over messages that predate the classifier service.

The live path is IncidentClassifierService (off the bus). This is the one-shot operator
job for history: it walks messages that have no incident row yet, runs the SAME cascade
(calibrated model + structural prefilter + operator rules), and stores the fired rows.

Keyset-paginated by message id: non-firing messages get no incident row, so the cursor
(``after_id``) — not the NOT-IN filter alone — is what advances past them. Re-runnable:
messages already classified are skipped by ``messages_without_incidents``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from eyenet.contracts.incident import IncidentRow
from eyenet.incidents import classifier, rules
from eyenet.telemetry import get_logger

if TYPE_CHECKING:
    from eyenet.storage.repository import BaseRepository

_log = get_logger()


async def run_backfill(
    storage: BaseRepository, *, batch_size: int = 64, limit: int | None = None
) -> tuple[int, int]:
    """Classify all un-classified messages. Returns (scanned, fired).

    ``batch_size`` is the inference/page size; ``limit`` caps total messages scanned
    (None = all). Model loads once (lru_cache in classifier._load)."""
    compiled = rules.compile_rules(await storage.list_incident_rules(enabled_only=True))
    model_version = classifier.model_dir().name
    after_id = None
    scanned = 0
    fired_total = 0

    while True:
        page = min(batch_size, limit - scanned) if limit is not None else batch_size
        if page <= 0:
            break
        rows = await storage.messages_without_incidents(limit=page, after_id=after_id)
        if not rows:
            break
        after_id = rows[-1][0]
        scanned += len(rows)

        # Model sees enrich_text(body, attachment filenames); prefilter/rules see raw body.
        att = await storage.attachment_files_by_message_ids([mid for mid, _b in rows])
        enriched = [classifier.enrich_text(body, att.get(mid)) for mid, body in rows]
        scored = classifier.classify_batch(enriched)
        now = datetime.now(UTC)
        incidents: list[object] = []  # ABC put_incidents_bulk is type-erased
        for (mid, text), scores in zip(rows, scored, strict=True):
            fired = (
                {s.label for s in scores if s.fired}
                | classifier.prefilter_labels(text)
                | rules.match_labels(text, compiled)
            )
            if not fired:
                continue
            incidents.append(
                IncidentRow(
                    message_id=mid,
                    labels=[s.label for s in scores if s.label in fired],  # head order
                    scores={s.label: s.prob for s in scores},
                    model_version=model_version,
                    classified_at=now,
                )
            )
        if incidents:
            await storage.put_incidents_bulk(incidents)
            fired_total += len(incidents)
        _log.info("incident.backfill_page", scanned=len(rows), fired=len(incidents))

    return scanned, fired_total
