# SPDX-License-Identifier: AGPL-3.0-or-later
"""Direct-call tests for the linker-maintenance run endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from eyenet.api.deps import CurrentUser
from eyenet.api.v1.linker.api_run import linker_detect_copypasta, linker_run_infra
from eyenet.contracts.enums import GroupKind, SourceKind, SystemUserRole
from eyenet.models import MessageTable
from eyenet.models._base import new_uuid7
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

_AD = (
    "We need a lot of USDT for long term cooperation, working hours nine to nine, "
    "supports IMPS UPI and bank cards, large and stable supplier in India, "
    "contact {h} to settle {n} today, third party payment no p2p f2f hybrid funds."
) * 2


@pytest.fixture
def storage() -> BaseRepository:
    return get_repository(in_memory=True)


def _user() -> CurrentUser:
    return CurrentUser(
        user_id=uuid4(),
        username="op",
        role=SystemUserRole.ADMIN,
        effective_scopes=frozenset({"write:linkage_decision"}),
        token_expires_at=None,
    )


async def _post(storage, src, gid, uid, body, n):
    a = await storage.upsert_actor(
        source_id=src,
        actor_key=f"a{uid}",
        platform_userid=uid,
        handle=None,
        display_name=f"b{uid}",
        seen_at=datetime.now(tz=UTC),
    )
    await storage.put_message(
        MessageTable(
            id=new_uuid7(),
            source_id=src,
            group_id=gid,
            actor_id=a,
            platform_msgid=f"m{n}",
            evidence_ref=f"e{n}",
            body=body,
            length_chars=len(body),
            length_words=len(body.split()),
            sent_at_source=datetime.now(tz=UTC),
            ingested_at=datetime.now(tz=UTC),
        ),
        None,
    )
    return a


@pytest.mark.unit
async def test_run_infra_and_detect_copypasta(storage: BaseRepository) -> None:
    now = datetime.now(tz=UTC)
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    gid = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHANNEL, title="g", seen_at=now
    )
    # 3 accounts posting the same ad (shared @handle in-body + copypasta template).
    await _post(storage, src, gid, "1", _AD.format(h="@wbpay_desk", n="100"), 1)
    await _post(storage, src, gid, "2", _AD.format(h="@wbpay_desk", n="200"), 2)
    await _post(storage, src, gid, "3", _AD.format(h="@wbpay_desk", n="300"), 3)

    infra = await linker_run_infra(_user(), storage)
    assert infra.proposed >= 1  # shared @wbpay_desk links them

    cp = await linker_detect_copypasta(_user(), storage)
    assert cp.flagged == 1  # one template, 3 posters
