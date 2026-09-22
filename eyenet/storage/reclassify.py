# SPDX-License-Identifier: AGPL-3.0-or-later
"""Return shape for the operator reclassify path (§4.9).

Backend-neutral, like :mod:`eyenet.storage.errors`: every backend's
``reclassify_{observation,attachment,document}`` returns this one type so the API
layer can build a ``ReclassificationResult`` without a second read. It carries
the row's post-write tier columns plus the id of the audit event the storage
method emitted, so the caller never has to reconstruct which audit row anchors
this change.

``operator_tier_override`` mirrors the row column (``None`` when the row was
never promoted, e.g. a same-tier no-op). ``audit_event_id`` is ``None`` on the
no-op path, where no reclassification audit event is written; on a real
promotion it is the emitted event's id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eyenet.contracts.enums import SensitivityTier


@dataclass(frozen=True)
class ReclassifyOutcome:
    prior_effective_tier: SensitivityTier
    classifier_tier: SensitivityTier
    operator_tier_override: SensitivityTier | None
    effective_tier: SensitivityTier
    reclassified_at: datetime
    audit_event_id: UUID | None


__all__ = ["ReclassifyOutcome"]
