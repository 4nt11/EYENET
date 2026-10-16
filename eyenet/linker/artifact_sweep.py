# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-validate stored crypto-address artifacts against the checksum gate.

:func:`eyenet.linker.indicators.extract` now rejects hex hashes that collide
with the base58 wallet patterns (see :mod:`eyenet.linker._address_checksum`),
but artifacts stored BEFORE that gate landed are still in
``infrastructure_artifact``. This sweep re-runs :func:`validate_address` over
every wallet-kind artifact and removes the ones that no longer validate (plus
their mention edges, actor rollup, derived graph edges, and search_document).

Idempotent and re-runnable: a clean corpus sweeps to zero deletions. Dry-run by
default — the caller passes ``apply=True`` to actually delete. Paging is done
read-only first (collect the invalid ids), THEN deletes, so in-place removal
never shifts the offset window out from under the scan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from eyenet.linker._address_checksum import validate_address

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from eyenet.storage.repository import BaseRepository

_log = structlog.get_logger()

# The crypto-address kinds the gate covers — must match validate_address's dispatch.
CRYPTO_KINDS = ("wallet_btc", "wallet_tron", "wallet_eth", "wallet_xmr")


@dataclass
class SweepReport:
    checked: int = 0
    invalid: int = 0
    deleted: int = 0
    # A few (kind, value) pairs for the operator to eyeball before --apply.
    invalid_samples: list[tuple[str, str]] = field(default_factory=list)


async def sweep_invalid_crypto_artifacts(
    storage: BaseRepository,
    *,
    apply: bool,
    batch: int = 500,
    sample_cap: int = 20,
) -> SweepReport:
    """Scan every wallet-kind artifact; drop the ones failing the checksum gate.

    The scan is keyset-paginated and aggregate-free (``artifacts_for_revalidation``)
    so it is O(n) over the corpus, not the O(n^2) of OFFSET + GROUP BY. With
    ``apply=False`` (default) nothing is deleted — the report says what WOULD go.
    With ``apply=True`` invalid artifacts are deleted in bulk, one chunk per
    round trip (search_document first, then the row + dependents).
    """
    report = SweepReport()
    invalid_ids: list[UUID] = []
    after_id: UUID | None = None
    while True:
        page = await storage.artifacts_for_revalidation(
            kinds=CRYPTO_KINDS, limit=batch, after_id=after_id
        )
        if not page:
            break
        for artifact_id, kind, value in page:
            after_id = artifact_id
            report.checked += 1
            if validate_address(kind, value):
                continue
            report.invalid += 1
            invalid_ids.append(artifact_id)
            if len(report.invalid_samples) < sample_cap:
                report.invalid_samples.append((kind, value))

    if apply and invalid_ids:
        for chunk in _chunks(invalid_ids, batch):
            for artifact_id in chunk:
                await storage.delete_search_document("artifact", artifact_id)
            report.deleted += await storage.delete_infrastructure_artifacts_bulk(chunk)
        _log.info(
            "artifact_checksum_sweep.applied",
            checked=report.checked,
            invalid=report.invalid,
            deleted=report.deleted,
        )
    return report


def _chunks(items: list[UUID], size: int) -> Sequence[list[UUID]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


__all__ = ["CRYPTO_KINDS", "SweepReport", "sweep_invalid_crypto_artifacts"]
