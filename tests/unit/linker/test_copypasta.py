# SPDX-License-Identifier: AGPL-3.0-or-later
"""Copypasta detection: masked fingerprint + batch detector + flagged read."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eyenet.contracts.enums import GroupKind, SourceKind
from eyenet.linker.copypasta import (
    TEMPLATE_MIN_CHARS,
    is_copypasta,
    template_fingerprint,
)
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository

# A long ad "template": same copy, only the amount + contact handle vary.
_AD = (
    "We need a lot of USDT for long term cooperation. Working hours 9am to 9pm. "
    "Supports IMPS UPI and bank cards. Game funds third party payment no p2p f2f. "
    "Large and stable supplier in India. Contact {handle} now to settle {amount} today."
) * 2


@pytest.mark.unit
def test_fingerprint_collapses_amount_and_handle() -> None:
    a = _AD.format(handle="@WBpay_mm1888", amount="500000")
    b = _AD.format(handle="@LV000098", amount="12345")
    assert template_fingerprint(a) == template_fingerprint(b)  # same template


@pytest.mark.unit
def test_fingerprint_distinguishes_real_content() -> None:
    a = _AD.format(handle="@x", amount="1")
    b = "totally different message about cats and the weather today, nothing to sell"
    assert template_fingerprint(a) != template_fingerprint(b)


@pytest.mark.unit
def test_is_copypasta_thresholds() -> None:
    assert is_copypasta(TEMPLATE_MIN_CHARS, 3) is True
    assert is_copypasta(TEMPLATE_MIN_CHARS - 1, 9) is False  # too short
    assert is_copypasta(TEMPLATE_MIN_CHARS, 2) is False  # too few posters


@pytest.mark.unit
async def test_detect_flags_template_and_gates() -> None:
    storage: BaseRepository = get_repository(in_memory=True)
    now = datetime.now(tz=UTC)
    src = await storage.upsert_source(kind=SourceKind.TELEGRAM, display_name="tg", created_at=now)
    gid = await storage.upsert_group(
        source_id=src, platform_groupid="@g", kind=GroupKind.CHANNEL, title="g", seen_at=now
    )
    n = 0

    async def _post(uid: str, body: str) -> None:
        nonlocal n
        n += 1
        a = await storage.upsert_actor(
            source_id=src,
            actor_key=f"actor:tg:{uid}",
            platform_userid=uid,
            handle=None,
            display_name=f"bot{uid}",
            seen_at=now,
        )
        from eyenet.models import MessageTable
        from eyenet.models._base import new_uuid7

        await storage.put_message(
            MessageTable(
                id=new_uuid7(),
                source_id=src,
                group_id=gid,
                actor_id=a,
                platform_msgid=f"m{n}",
                evidence_ref=f"telegram:g:{n}",
                body=body,
                length_chars=len(body),
                length_words=len(body.split()),
                sent_at_source=now,
                ingested_at=now,
            ),
            None,
        )

    # The same long ad from 3 distinct accounts -> copypasta.
    await _post("101", _AD.format(handle="@a", amount="1"))
    await _post("102", _AD.format(handle="@b", amount="2"))
    await _post("103", _AD.format(handle="@c", amount="3"))
    # A unique, short message -> not copypasta.
    await _post("104", "hey what's the rate today?")

    flagged = await storage.detect_copypasta_templates()
    assert flagged == 1

    fps = await storage.flagged_copypasta_fingerprints()
    assert template_fingerprint(_AD.format(handle="@z", amount="9")) in fps  # a 4th variant matches
    assert template_fingerprint("hey what's the rate today?") not in fps
