# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ownership gate for saved graphs.

Saved graphs are per-operator private workspaces (``graphs_list`` only ever returns
the caller's own). The by-id handlers must enforce the same ownership, or an
operator could read or mutate another's investigation graph by guessing/holding its
id. A non-owner gets 404 (``ResourceNotFound``), not 403, so the endpoint does not
even confirm that another operator's graph exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from eyenet.api.deps import ResourceNotFound

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.api.deps import CurrentUser
    from eyenet.contracts.investigation_graph import InvestigationGraphRow
    from eyenet.storage.repository import BaseRepository


async def owned_graph_or_404(
    storage: BaseRepository, current_user: CurrentUser, graph_id: UUID
) -> InvestigationGraphRow:
    """Return the graph iff it exists AND belongs to the caller; else raise 404."""
    row = await storage.get_investigation_graph(graph_id)
    if row is None or row.created_by_user_id != current_user.user_id:
        raise ResourceNotFound("graph")
    return row
