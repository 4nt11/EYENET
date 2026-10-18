# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas for the runtime operator-settings admin surface (/v1/settings)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SettingValue(BaseModel):
    """One runtime setting's effective value (stored value, or the registered default)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: str
    is_default: bool
    description: str


class SettingUpdate(BaseModel):
    """Admin update body for a setting value (validated against the key's registry spec)."""

    model_config = ConfigDict(extra="forbid")

    value: str
