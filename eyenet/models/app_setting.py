# SPDX-License-Identifier: AGPL-3.0-or-later
"""AppSettingTable — a tiny key/value store for runtime-tunable operator settings.

Not config.toml (ships with the image, needs a redeploy) and not a per-identity
field: these are GLOBAL knobs an admin flips at runtime through the API and that
long-running services re-read without a restart. The first key is
``telegram.attachment_max_bytes`` (the attachment download size gate). Value is an
opaque string the caller parses (int-as-str here); keeping it a string avoids a
JSON column + typed-per-key churn for what is a handful of scalars.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class AppSettingTable(SQLModel, table=True):
    __tablename__ = "app_setting"

    key: str = Field(primary_key=True, max_length=128)
    value: str
    updated_at: datetime
    updated_by: str | None = None


__all__ = ["AppSettingTable"]
