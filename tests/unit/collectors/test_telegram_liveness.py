# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the telethon-free group-liveness classifier.

Mirrors the import-free style of test_telegram_join: no telethon, no network —
just the string→verdict mapping that decides whether a monitored group is DEAD.
"""

from __future__ import annotations

import pytest

from eyenet.collectors.telegram._liveness import GroupLiveness, classify_liveness

pytestmark = pytest.mark.unit


def test_success_is_alive() -> None:
    assert classify_liveness(None) is GroupLiveness.ALIVE


@pytest.mark.parametrize(
    "exc_name",
    ["UsernameNotOccupiedError", "UsernameInvalidError", "ValueError"],
)
def test_gone_username_is_deleted(exc_name: str) -> None:
    # @Synq1xxs raised "Nobody is using this username" = UsernameNotOccupiedError.
    assert classify_liveness(exc_name) is GroupLiveness.DELETED


def test_channel_private_is_unavailable() -> None:
    assert classify_liveness("ChannelPrivateError") is GroupLiveness.UNAVAILABLE


@pytest.mark.parametrize(
    "exc_name",
    ["FloodWaitError", "TimeoutError", "ConnectionError", "SomeUnknownRpcError"],
)
def test_transient_or_unknown_stays_alive(exc_name: str) -> None:
    # Conservative: never kill a live group on an error we don't understand.
    assert classify_liveness(exc_name) is GroupLiveness.ALIVE


def test_nonalive_reasons_fit_left_reason_column() -> None:
    # left_reason is max_length=64; the verdict values are used verbatim as it.
    for v in GroupLiveness:
        assert len(v.value) <= 64
