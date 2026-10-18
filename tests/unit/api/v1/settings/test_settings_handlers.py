# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET/PUT /v1/settings/{key} handlers + the app_settings registry — direct-call."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eyenet.api.deps import ResourceNotFound, UnprocessableError
from eyenet.api.v1.schemas.settings import SettingUpdate
from eyenet.api.v1.settings.api_get_setting import settings_get
from eyenet.api.v1.settings.api_set_setting import settings_set
from eyenet.app_settings import TELEGRAM_ATTACHMENT_MAX_BYTES, default_value

pytestmark = pytest.mark.unit


class _FakeStorage:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._kv = dict(initial or {})
        self.writes: list[tuple[str, str, str | None]] = []

    async def get_setting(self, key: str) -> str | None:
        return self._kv.get(key)

    async def set_setting(self, key: str, value: str, *, updated_by: str | None = None) -> None:
        self._kv[key] = value
        self.writes.append((key, value, updated_by))


def _user():
    return SimpleNamespace(user_id=uuid4(), username="op.admin")


def test_get_returns_default_when_unset() -> None:
    out = asyncio.run(
        settings_get(key=TELEGRAM_ATTACHMENT_MAX_BYTES, _=_user(), storage=_FakeStorage())
    )
    assert out.value == default_value(TELEGRAM_ATTACHMENT_MAX_BYTES)
    assert out.is_default is True


def test_get_returns_stored_value() -> None:
    st = _FakeStorage({TELEGRAM_ATTACHMENT_MAX_BYTES: "1048576"})
    out = asyncio.run(settings_get(key=TELEGRAM_ATTACHMENT_MAX_BYTES, _=_user(), storage=st))
    assert out.value == "1048576"
    assert out.is_default is False


def test_get_unknown_key_is_404() -> None:
    with pytest.raises(ResourceNotFound):
        asyncio.run(settings_get(key="bogus.key", _=_user(), storage=_FakeStorage()))


def test_set_validates_and_stores_coerced() -> None:
    st = _FakeStorage()
    out = asyncio.run(
        settings_set(
            key=TELEGRAM_ATTACHMENT_MAX_BYTES,
            body=SettingUpdate(value="2097152"),
            current_user=_user(),
            storage=st,
        )
    )
    assert out.value == "2097152"
    assert st.writes == [(TELEGRAM_ATTACHMENT_MAX_BYTES, "2097152", "op.admin")]


def test_set_rejects_bad_value() -> None:
    with pytest.raises(UnprocessableError):
        asyncio.run(
            settings_set(
                key=TELEGRAM_ATTACHMENT_MAX_BYTES,
                body=SettingUpdate(value="-5"),
                current_user=_user(),
                storage=_FakeStorage(),
            )
        )


def test_set_unknown_key_is_404() -> None:
    with pytest.raises(ResourceNotFound):
        asyncio.run(
            settings_set(
                key="bogus.key",
                body=SettingUpdate(value="1"),
                current_user=_user(),
                storage=_FakeStorage(),
            )
        )
