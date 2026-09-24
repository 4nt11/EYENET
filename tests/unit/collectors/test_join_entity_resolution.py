# SPDX-License-Identifier: AGPL-3.0-or-later
"""_resolve_public_entity: @username resolves directly; a bare numeric id (a group
with no public username) falls back to the account's dialog list, which carries the
access_hash for groups the account is already in. Regression for a join that failed
with `Cannot find any entity corresponding to "<numeric id>"`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eyenet.bus.memory import MemoryBus
from eyenet.collectors.telegram.real import TelegramCollector
from eyenet.storage.factory import get_repository


class _StubPool:
    async def claim(self, name: str) -> object:
        raise NotImplementedError

    async def release(self, name: str, *, new_state: object) -> None: ...
    async def freeze_all(self) -> None: ...


class _FakeClient:
    """get_entity resolves @usernames; a numeric string raises like telethon does."""

    def __init__(self, dialogs: list[object]) -> None:
        self._dialogs = dialogs

    async def get_entity(self, ref: str) -> object:
        if isinstance(ref, str) and ref.startswith("@"):
            return SimpleNamespace(id=999, username=ref[1:])
        raise ValueError(f'Cannot find any entity corresponding to "{ref}"')

    async def iter_dialogs(self):  # type: ignore[no-untyped-def]
        for d in self._dialogs:
            yield d


def _collector(client: _FakeClient) -> TelegramCollector:
    c = TelegramCollector(
        bus=MemoryBus(),
        storage=get_repository(in_memory=True),
        pool=_StubPool(),  # type: ignore[arg-type]
        identity_name="tgtest",
    )
    c._client = client  # type: ignore[assignment]
    return c


@pytest.mark.unit
async def test_resolve_username_direct() -> None:
    c = _collector(_FakeClient(dialogs=[]))
    ent = await c._resolve_public_entity("@cvv190log")
    assert getattr(ent, "username", None) == "cvv190log"


@pytest.mark.unit
async def test_resolve_numeric_via_dialogs() -> None:
    # The account is a member: the dialog carries the real entity (id 3914110555).
    target = SimpleNamespace(id=3914110555, title="target")
    other = SimpleNamespace(id=42, title="noise")
    c = _collector(
        _FakeClient(dialogs=[SimpleNamespace(entity=other), SimpleNamespace(entity=target)])
    )
    ent = await c._resolve_public_entity("3914110555")
    assert ent is target


@pytest.mark.unit
async def test_resolve_numeric_not_a_member_raises() -> None:
    c = _collector(_FakeClient(dialogs=[SimpleNamespace(entity=SimpleNamespace(id=42))]))
    with pytest.raises(ValueError, match="no dialog matches"):
        await c._resolve_public_entity("3914110555")
