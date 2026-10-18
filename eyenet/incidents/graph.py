# SPDX-License-Identifier: AGPL-3.0-or-later
"""Graph projection of incidents: one incident node per MESSAGE (the effective
classification), with a deterministic id.

An incident is per-message (model prediction and/or operator correction collapse to one
effective view). Its graph/search id is a deterministic ``uuid5`` of the message id, so it
is stable across re-classification and relabel, and distinct from the message's own id
(they must never collide as canvas nodes). Shared by the enrichment, the search indexer,
and the backfill so all three agree on the id.
"""

from __future__ import annotations

import uuid

# Fixed namespace for incident node ids (never change it, or every id shifts).
_INCIDENT_NS = uuid.UUID("06ad0000-0000-5000-8000-eecec1de0000")


def incident_node_id(message_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_INCIDENT_NS, str(message_id))
