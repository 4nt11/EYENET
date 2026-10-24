# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse sink for extracted ULP credentials.

Thin wrapper over clickhouse-connect (HTTP). Owns the ``stealer.creds``
ReplacingMergeTree schema (dedup key == ``(host, login, password)``) and a batched
insert from ulpextract's TSV columns. clickhouse-connect is an OPTIONAL dep shipped
in the stealer profile image, so it's imported lazily — the core stack never needs it.

Config via env: ``EYENET_CLICKHOUSE_HOST`` (default "clickhouse"), ``_PORT`` (8123),
``_USER`` (default "default"), ``_PASSWORD`` (default ""), ``_DB`` (default "stealer").
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from clickhouse_connect.driver.client import Client

# ulpextract emits these columns, tab-separated, in this order.
_COLUMNS = ["host", "url", "login", "password", "scheme", "tld", "source", "ip_class"]

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"
# ReplacingMergeTree collapses rows with identical (host, login, password) on merge,
# keeping max(ingested). url/scheme/tld/source/ip_class are payload, not identity.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {db}.creds
(
    host     String,
    url      String,
    login    String,
    password String,
    scheme   LowCardinality(String) DEFAULT '',
    tld      LowCardinality(String) DEFAULT '',
    source   LowCardinality(String) DEFAULT '',
    ip_class LowCardinality(String) DEFAULT '',
    ingested DateTime               DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested)
ORDER BY (host, login, password)
"""


class ClickHouseCredsSink:
    """Connection + schema + batched credential insert for ``<db>.creds``."""

    def __init__(self) -> None:
        self._db = os.environ.get("EYENET_CLICKHOUSE_DB", "stealer")
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is not None:
            return self._client
        import clickhouse_connect  # noqa: PLC0415 — optional dep, stealer profile only

        self._client = clickhouse_connect.get_client(
            host=os.environ.get("EYENET_CLICKHOUSE_HOST", "clickhouse"),
            port=int(os.environ.get("EYENET_CLICKHOUSE_PORT", "8123")),
            username=os.environ.get("EYENET_CLICKHOUSE_USER", "default"),
            password=os.environ.get("EYENET_CLICKHOUSE_PASSWORD", ""),
        )
        return self._client

    def ensure_schema(self) -> None:
        """Create the database + creds table if absent (idempotent)."""
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(_CREATE_TABLE.format(db=self._db))

    def insert_rows(self, rows: Iterable[list[str]]) -> int:
        """Insert cred rows (each an 8-value list matching ulpextract's columns).
        Returns the number inserted. Caller batches; this is one INSERT per call."""
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(f"{self._db}.creds", batch, column_names=_COLUMNS)
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = ["ClickHouseCredsSink"]
