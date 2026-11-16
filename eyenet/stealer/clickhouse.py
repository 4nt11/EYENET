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
_COLUMNS = [
    "host", "url", "login", "password", "scheme", "tld", "source", "ip_class", "source_file"
]

_CREATE_DB = "CREATE DATABASE IF NOT EXISTS {db}"
# ReplacingMergeTree collapses rows with identical (host, login, password) on merge,
# keeping max(ingested). url/scheme/tld/source/ip_class are payload, not identity.
#
# `storage_policy` is injected by _storage_policy_clause() from the
# EYENET_CLICKHOUSE_STORAGE_POLICY env var: on prod lite this is
# 'wasabi_primary' (see clickhouse/config.d/wasabi-storage.xml) so the corpus
# lives on Wasabi with a local SSD cache; on dev the var is unset and CH
# uses the implicit `default` local policy. Changing the policy of an
# existing table is a separate `ALTER TABLE creds MODIFY SETTING
# storage_policy=...` + data move, not a redeploy.
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {db}.creds
(
    host        String,
    url         String,
    login       String,
    password    String,
    scheme      LowCardinality(String) DEFAULT '',
    tld         LowCardinality(String) DEFAULT '',
    source      LowCardinality(String) DEFAULT '',
    ip_class    LowCardinality(String) DEFAULT '',
    source_file String                 DEFAULT '',
    ingested    DateTime               DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested)
ORDER BY (host, login, password)
{storage_policy_clause}
"""

# Schema-upgrade DDL idempotently applied after _CREATE_TABLE on every
# ``ensure_schema`` call. Each statement must be an ``ALTER TABLE ... IF
# NOT EXISTS`` (or MODIFY-COLUMN-safe equivalent) so re-running against an
# already-upgraded table is a no-op. CH 24.x supports IF NOT EXISTS on
# ADD COLUMN. Keep oldest-first; never remove a line, even after it has
# been in every running cluster for a release, so a long-skipped operator
# upgrading across multiple versions still catches it.
_ALTER_TABLE = (
    # v1.2.5 - per-record source file (the ulpextract inner path). Earlier
    # releases dropped this on the floor via fields[6] overwrite; now kept
    # as its own column so a bad row traces back to the file that produced
    # it, and the v1.3.0 infections join has a key to attach on.
    "ALTER TABLE {db}.creds ADD COLUMN IF NOT EXISTS source_file String DEFAULT ''",
)


def _storage_policy_clause() -> str:
    """`SETTINGS storage_policy='<name>'` when EYENET_CLICKHOUSE_STORAGE_POLICY
    is set, empty string otherwise. Kept dumb on purpose: CH itself validates
    the name at CREATE TABLE and fails loud if the policy does not exist."""
    policy = os.environ.get("EYENET_CLICKHOUSE_STORAGE_POLICY", "").strip()
    if not policy:
        return ""
    # CH policy names are identifiers (letters/digits/underscore); reject
    # anything else so an operator typo can never land as SQL.
    if not all(c.isalnum() or c == "_" for c in policy):
        raise ValueError(
            f"EYENET_CLICKHOUSE_STORAGE_POLICY={policy!r} is not a valid policy name "
            "(alphanumeric + underscore only)"
        )
    return f"SETTINGS storage_policy = '{policy}'"


def clickhouse_db() -> str:
    return os.environ.get("EYENET_CLICKHOUSE_DB", "stealer")


def get_clickhouse_client() -> Client:
    """A clickhouse-connect client from EYENET_CLICKHOUSE_* env. Shared by the creds
    sink (processor) and the read API (search/stats)."""
    import clickhouse_connect  # noqa: PLC0415 — dep present in core + stealer images

    return clickhouse_connect.get_client(
        host=os.environ.get("EYENET_CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("EYENET_CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("EYENET_CLICKHOUSE_USER", "default"),
        password=os.environ.get("EYENET_CLICKHOUSE_PASSWORD", ""),
    )


class ClickHouseCredsSink:
    """Connection + schema + batched credential insert for ``<db>.creds``."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def ensure_schema(self) -> None:
        """Create the database + creds table if absent AND apply the idempotent
        ALTER chain (``_ALTER_TABLE``) so an older cluster upgrades in place
        without an operator action."""
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(
            _CREATE_TABLE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )
        for alter in _ALTER_TABLE:
            client.command(alter.format(db=self._db))

    def insert_rows(self, rows: Iterable[list[str]]) -> int:
        """Insert cred rows (each a value list matching ``_COLUMNS``). Returns
        the number inserted. Caller batches; this is one INSERT per call."""
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(f"{self._db}.creds", batch, column_names=_COLUMNS)
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# v1.2.6 observability side channel. One row per file in every per-victim folder
# of every archive, so operators can answer "what files do we SEE that we are
# not parsing" from a SQL query instead of spelunking blobs by hand. The table
# is intentionally thin (no per-line counts; v1.3.0 adds those when the Go
# extractor is touched for the rule engine). ReplacingMergeTree collapses
# re-scans of the same file in the same archive on dedup.
_FILE_AUDIT_CREATE = """
CREATE TABLE IF NOT EXISTS {db}.file_audit
(
    archive_sha256      FixedString(64),
    rel_path            String,
    filename            String,
    size_bytes          UInt64,
    file_sha256         FixedString(64),
    heuristic_kind      LowCardinality(String),
    extractor_touched   UInt8    DEFAULT 0,
    rows_emitted        UInt32   DEFAULT 0,
    approx_banner_hits  UInt32   DEFAULT 0,
    approx_null_pw_hits UInt32   DEFAULT 0,
    sample_head         String,
    parsed_at           DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(parsed_at)
ORDER BY (archive_sha256, rel_path)
{storage_policy_clause}
"""

_FILE_AUDIT_COLUMNS = [
    "archive_sha256",
    "rel_path",
    "filename",
    "size_bytes",
    "file_sha256",
    "heuristic_kind",
    "extractor_touched",
    "rows_emitted",
    "approx_banner_hits",
    "approx_null_pw_hits",
    "sample_head",
]


class FileAuditSink:
    """CH sink for the file_audit observability table. Mirrors
    ``ClickHouseCredsSink`` shape so the pipeline can init + call insert_rows
    the same way. Separate class so a CH misconfig on file_audit never breaks
    the credential insert path."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _connect(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def ensure_schema(self) -> None:
        """Create database + file_audit table if absent. Idempotent."""
        client = self._connect()
        client.command(_CREATE_DB.format(db=self._db))
        client.command(
            _FILE_AUDIT_CREATE.format(
                db=self._db,
                storage_policy_clause=_storage_policy_clause(),
            )
        )

    def insert_rows(self, rows: Iterable[list[Any]]) -> int:
        batch: list[list[Any]] = list(rows)
        if not batch:
            return 0
        self._connect().insert(
            f"{self._db}.file_audit", batch, column_names=_FILE_AUDIT_COLUMNS
        )
        return len(batch)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


__all__ = [
    "ClickHouseCredsSink",
    "FileAuditSink",
    "clickhouse_db",
    "get_clickhouse_client",
]
