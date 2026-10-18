# SPDX-License-Identifier: AGPL-3.0-or-later
"""PUT /v1/settings/{key} - update a runtime operator setting (admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eyenet.api.deps import (
    CurrentUser,
    RequireScope,
    ResourceNotFound,
    UnprocessableError,
    get_storage,
)
from eyenet.api.v1.schemas.settings import SettingUpdate, SettingValue
from eyenet.app_settings import SETTINGS, is_known, validate_value
from eyenet.storage.repository import BaseRepository

router = APIRouter(tags=["settings"])


@router.put(
    "/settings/{key}",
    operation_id="settings_set",
    response_model=SettingValue,
    status_code=200,
)
async def settings_set(
    key: str,
    body: SettingUpdate,
    current_user: Annotated[CurrentUser, Depends(RequireScope("admin:settings"))],
    storage: Annotated[BaseRepository, Depends(get_storage)],
) -> SettingValue:
    if not is_known(key):
        raise ResourceNotFound("setting")
    try:
        coerced = validate_value(key, body.value)
    except ValueError as exc:
        raise UnprocessableError(f"invalid value for {key}: {exc}") from exc
    await storage.set_setting(key, coerced, updated_by=current_user.username)
    return SettingValue(
        key=key, value=coerced, is_default=False, description=SETTINGS[key].description
    )
