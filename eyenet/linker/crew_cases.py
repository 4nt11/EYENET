# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open Cases from crews — turn a shared-infra crew into an investigation.

A crew (connected component of the shared-infrastructure graph) is a candidate
criminal operation; the Case is EYENET's investigation container. This bridges
them: an operator promotes a crew, and big high-confidence crews are opened
automatically. Idempotent via ``CaseTable.crew_key`` so re-runs don't spawn
duplicate cases for the same crew.

See ``development/linker-antispam-spec.md`` §3 and the Case API (§4.10).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast
from uuid import UUID

from eyenet.contracts.enums import CaseRoleOnCase, CaseSubjectKind, LinkageState
from eyenet.linker.crews import Crew, build_crews

if TYPE_CHECKING:
    from eyenet.contracts.attribution import LinkageRow
    from eyenet.contracts.case import CaseRow
    from eyenet.storage.repository import BaseRepository

# Auto-open thresholds: only large, high-confidence crews become cases without an
# operator click; the long tail is operator-promote (spec §3 decision).
AUTO_MIN_SIZE = 8
AUTO_MIN_SCORE = 0.8

_EDGE_LIMIT = 100_000


def _pretty(tok: str) -> str:
    for pfx, rep in (
        ("handle:", "@"),
        ("tme:", "t.me/"),
        ("wallet_trx:", "TRX "),
        ("wallet_evm:", "EVM "),
    ):
        if tok.startswith(pfx):
            return rep + tok[len(pfx) :]
    return tok


def crew_key_for(top_infra: list[str], members: list[UUID]) -> str:
    """Stable identity for a crew (idempotency key). The dominant shared indicator
    when present (a crew's defining infrastructure is stable across runs); else a
    hash of the sorted member set."""
    if top_infra:
        return top_infra[0]
    digest = hashlib.sha256(",".join(sorted(str(m) for m in members)).encode()).hexdigest()
    return f"crew:{digest[:16]}"


def crew_case_title(top_infra: list[str], size: int) -> str:
    """Human title for a nameless crew: its dominant infra, else its size."""
    if top_infra:
        return f"Crew · {_pretty(top_infra[0])}"
    return f"Crew of {size} accounts"


async def open_case_for_crew(
    storage: BaseRepository,
    *,
    members: list[UUID],
    top_infra: list[str],
    opened_by_user_id: UUID,
    service: str,
    instance_id: str,
    title: str | None = None,
) -> CaseRow:
    """Open (or return the existing) Case for a crew and attach its actors.

    Idempotent: if a case already carries this crew's ``crew_key`` it is returned
    unchanged. Otherwise a new OPEN case is created (``crew_key`` set) and every
    member actor is added as an ACTOR case member."""
    key = crew_key_for(top_infra, members)
    existing = await storage.get_case_by_crew_key(key)
    if existing is not None:
        return existing
    case = await storage.create_case(
        title=title or crew_case_title(top_infra, len(members)),
        description=(
            "Auto-derived from a shared-infrastructure crew. Shared indicators: "
            + ", ".join(_pretty(t) for t in top_infra[:8])
            if top_infra
            else "Shared-infrastructure crew."
        ),
        opened_by_user_id=opened_by_user_id,
        service=service,
        instance_id=instance_id,
        crew_key=key,
    )
    # Opener is OWNER so they satisfy the §4.10.4 case-visibility predicate.
    await storage.add_case_collaborator(
        case_id=case.id,
        user_id=opened_by_user_id,
        role=CaseRoleOnCase.OWNER,
        granted_by_user_id=opened_by_user_id,
        service=service,
        instance_id=instance_id,
    )
    for actor_id in members:
        await storage.add_case_member(
            case_id=case.id,
            subject_kind=CaseSubjectKind.ACTOR,
            subject_id=actor_id,
            added_by_user_id=opened_by_user_id,
            reason="crew member (shared infrastructure)",
            service=service,
            instance_id=instance_id,
        )
    return case


async def _load_crews(storage: BaseRepository) -> list[Crew]:
    links = cast(
        "list[LinkageRow]",
        await storage.list_linkages(
            state=LinkageState.PROPOSED, method="shared_infra", limit=_EDGE_LIMIT
        ),
    )
    edges = [
        (
            link.actor_a_id,
            link.actor_b_id,
            link.score,
            [str(v) for v in cast("list[object]", link.evidence.get("shared", []))],
        )
        for link in links
    ]
    return build_crews(edges)


async def open_cases_for_big_crews(
    storage: BaseRepository,
    *,
    opened_by_user_id: UUID,
    service: str,
    instance_id: str,
    min_size: int = AUTO_MIN_SIZE,
    min_score: float = AUTO_MIN_SCORE,
) -> int:
    """Auto-open a Case for every crew that is large AND high-confidence, skipping
    crews that already have one. Returns the number of NEW cases opened."""
    opened = 0
    for crew in await _load_crews(storage):
        if len(crew.members) < min_size or crew.max_score < min_score:
            continue
        key = crew_key_for(list(crew.top_infra), list(crew.members))
        if await storage.get_case_by_crew_key(key) is not None:
            continue
        await open_case_for_crew(
            storage,
            members=list(crew.members),
            top_infra=list(crew.top_infra),
            opened_by_user_id=opened_by_user_id,
            service=service,
            instance_id=instance_id,
        )
        opened += 1
    return opened


__all__ = [
    "AUTO_MIN_SCORE",
    "AUTO_MIN_SIZE",
    "crew_case_title",
    "crew_key_for",
    "open_case_for_crew",
    "open_cases_for_big_crews",
]
