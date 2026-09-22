#!/usr/bin/env python
"""Seed the real DB with demo data so the wired UI has something to show.

Storage-direct (bypasses the API): run it with the API server STOPPED, or
expect brief SQLite lock retries. Additive and re-runnable — upserts are
idempotent; cases/linkages/candidates simply accumulate on repeat runs.

    .venv/bin/python development/demo_seed.py --data-dir data --user anti

Seeds: a Telegram source + group + actors + messages, a collector identity +
collector, a proposed linkage between two actors, a case with those actors as
members, and one group candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Running a script puts its own dir on sys.path, not the repo root — add the
# root so we can reuse the canonical test seed helper.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eyenet.contracts.enums import (  # noqa: E402
    CaseRoleOnCase,
    CaseSubjectKind,
    MentionKind,
    SourceKind,
)
from eyenet.storage.factory import get_repository  # noqa: E402
from eyenet.storage.repository import BaseRepository  # noqa: E402
from tests._seed import seed_telegram_fixture  # noqa: E402

_SVC = {"service": "demo-seed", "instance_id": "seed-0"}

_RECORDS = [
    {"actor_key": "tg:krieg_wolf", "platform_msgid": "1001", "body": "loader staged, dropping tonight"},
    {"actor_key": "tg:silent_relay", "platform_msgid": "1002", "body": "confirmed, relay is warm"},
    {"actor_key": "tg:krieg_wolf", "platform_msgid": "1003", "body": "use the finance list first"},
    {"actor_key": "tg:ghostpost", "platform_msgid": "1004", "body": "lurking, will mirror the domains"},
    {"actor_key": "tg:silent_relay", "platform_msgid": "1005", "body": "same infra as last week"},
]


async def _seed(storage: BaseRepository, username: str) -> None:
    now = datetime.now(UTC)
    tag = now.strftime("%H%M%S")  # keep per-run names unique so re-runs don't collide

    user = await storage.get_system_user_by_username(username)
    if user is None:
        raise SystemExit(f"user {username!r} not found — create it with `eyenet user create`")
    uid = user.id

    # 1. Source + group + actors + messages.
    source_id, group_id, actor_ids = await seed_telegram_fixture(
        storage, _RECORDS, now, source_display_name="telegram:loader-ops", group_title="loader-ops"
    )
    actors = list(actor_ids.values())
    print(f"seeded source + group + {len(actors)} actors + {len(_RECORDS)} messages")

    # 2. Collector identity + collector.
    identity = await storage.create_identity(
        name=f"demo-monitor-{tag}", source_id=source_id, session_path="/dev/null"
    )
    collector = await storage.create_collector(
        instance_name=f"tg-collector-{tag}",
        kind=SourceKind.TELEGRAM,
        source_id=source_id,
        identity_id=identity.id,
        config={"telegram_api_id": 0},
        created_at=now,
        created_by_user_id=uid,
        notes="seeded demo collector",
    )
    print(f"seeded identity {identity.id} + collector {collector.id}")

    # 3. Proposed linkage between the two chattiest actors.
    linkage = await storage.insert_proposed_linkage(
        actors[0], actors[1], method="stylometry", score=0.82,
        evidence={"reason": "shared loader phrasing", "shared_ngrams": 14},
    )
    print(f"seeded proposed linkage {linkage.id} ({actors[0]} <-> {actors[1]})")

    # 4. A case with those actors as members.
    case = await storage.create_case(
        title="Demo · loader campaign (seeded)",
        description="Seeded demo case with actor members and a linkage.",
        opened_by_user_id=uid,
        now=now,
        **_SVC,
    )
    # The API's create adds the creator as an owner-collaborator; case reads
    # require it (visibility predicate §4.10.4). Direct create_case skips it.
    await storage.add_case_collaborator(
        case_id=case.id, user_id=uid, role=CaseRoleOnCase.OWNER,
        granted_by_user_id=uid, now=now, **_SVC,
    )
    for actor in actors[:3]:
        await storage.add_case_member(
            case_id=case.id, subject_kind=CaseSubjectKind.ACTOR, subject_id=actor,
            added_by_user_id=uid, reason="seeded demo evidence membership", now=now, **_SVC,
        )
    print(f"seeded case {case.id} + {min(3, len(actors))} members")

    # 5. One group candidate (a mention observed by the collector).
    cand, _mention = await storage.record_candidate_mention(
        source_id=source_id,
        platform_groupid="-100200300",
        observed_by_collector_id=collector.id,
        observed_in_group_id=group_id,
        seed_root_id=None,
        depth_from_root=1,
        mention_evidence_ref=f"telegram:{group_id}:1003",
        mention_kind=next(iter(MentionKind)),
        mentioned_at_source=now,
        mentioned_at_ingest=now,
        mentioning_actor_id=actors[0],
        display_name_hint="loader-ops-mirror",
    )
    print(f"seeded candidate {cand.id}")

    await storage.close()
    print("done.")


async def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--user", default="anti", help="username to attribute seeded writes to")
    args = ap.parse_args()
    storage = get_repository(data_dir=Path(args.data_dir))
    await _seed(storage, args.user)


if __name__ == "__main__":
    asyncio.run(_main())
