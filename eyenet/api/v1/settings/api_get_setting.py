# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/settings/{key} - read a runtime operator setting (admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import CurrentUser, RequireScope, ResourceNotFound, get_storage
from eyenet.api.v1.schemas.settings import SettingValue
from eyenet.app_settings import SETTINGS, default_value, is_known
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["settings"])


@router.get(
    "/settings/{key}",
    operation_id="settings_get",
    response_model=SettingValue,
    status_code=200,
)
async def settings_get(
    key: str,
    _: Annotated[CurrentUser, Depends(RequireScope("admin:settings"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> SettingValue:
    if not is_known(key):
        raise ResourceNotFound("setting")
    stored = await storage.get_setting(key)
    return SettingValue(
        key=key,
        value=stored if stored is not None else default_value(key),
        is_default=stored is None,
        description=SETTINGS[key].description,
    )
