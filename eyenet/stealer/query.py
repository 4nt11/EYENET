# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read side of the ULP corpus: stats + credential search over ClickHouse stealer.creds.

Backs the read:stealer API (overview charts + host search). Queries are parameterized
(clickhouse-connect bound params) so the operator's search term can't inject SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from eyenet.stealer.clickhouse import clickhouse_db, get_clickhouse_client

if TYPE_CHECKING:
    from clickhouse_connect.driver.client import Client


# ClickHouse's error code for "table does not exist". Used to distinguish
# "corpus not initialized yet" (no stealer channels collected from, so
# ensure_schema() has never run) from "CH is unreachable". The former is a
# normal operational state -- empty UI, operator hint -- not a 503.
_CH_UNKNOWN_TABLE = 60


class StealerCorpusUninitializedError(Exception):
    """Raised when the corpus table does not exist yet.

    Semantics: CH is reachable, the DDL just has not been created because
    the stealer-processor has not yet seen a message that triggers
    ``ClickHouseCredsSink.ensure_schema()``. The API layer turns this into
    an empty-but-successful response with an ``initialized=False`` marker
    the dashboard can render as a "add a stealer channel" nudge.
    """


@dataclass(frozen=True, slots=True)
class Bucket:
    key: str
    count: int


@dataclass(frozen=True, slots=True)
class StealerStats:
    total_creds: int
    unique_creds: int
    distinct_hosts: int
    by_scheme: list[Bucket] = field(default_factory=list)
    by_tld: list[Bucket] = field(default_factory=list)  # ccTLD of the service host (country-ish)
    top_hosts: list[Bucket] = field(default_factory=list)


def _is_unknown_table(exc: BaseException) -> bool:
    """True iff `exc` is clickhouse-connect raising for a missing table.

    clickhouse-connect bundles the CH server error code in the exception
    message (e.g. ``Code: 60. DB::Exception: Unknown table ...``) and does
    not expose it as a structured attribute, so we match on the code number
    at the start. We require BOTH the code AND the keyword to avoid
    collisions with other code-60-flavoured errors in future CH versions.
    """
    msg = str(exc)
    return f"Code: {_CH_UNKNOWN_TABLE}." in msg and "UNKNOWN_TABLE" in msg


@dataclass(frozen=True, slots=True)
class CredRow:
    host: str
    url: str
    login: str
    password: str
    scheme: str
    tld: str


class StealerCredsReader:
    """Aggregate + search queries over ``<db>.creds``. One client, reused."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _c(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def _buckets(self, sql: str, params: dict[str, object]) -> list[Bucket]:
        rows = self._c().query(sql, parameters=params).result_rows
        return [Bucket(key=str(r[0]), count=int(r[1])) for r in rows]

    def stats(self, *, top: int = 20) -> StealerStats:
        # Fully parameterized: the db is a bound {Identifier}, the limit a bound UInt32,
        # no string interpolation, so no injection surface even on the (trusted) db name.
        db: dict[str, object] = {"db": self._db}
        db_top: dict[str, object] = {"db": self._db, "top": int(top)}
        try:
            scalars = self._c().query(
                "SELECT count(), uniqExact((host,login,password)), uniqExact(host) "
                "FROM {db:Identifier}.creds",
                parameters=db,
            ).result_rows[0]
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.creds table does not exist yet"
                ) from exc
            raise
        return StealerStats(
            total_creds=int(scalars[0]),
            unique_creds=int(scalars[1]),
            distinct_hosts=int(scalars[2]),
            by_scheme=self._buckets(
                "SELECT scheme, count() c FROM {db:Identifier}.creds "
                "GROUP BY scheme ORDER BY c DESC",
                db,
            ),
            by_tld=self._buckets(
                "SELECT tld, count() c FROM {db:Identifier}.creds WHERE tld != '' "
                "GROUP BY tld ORDER BY c DESC LIMIT {top:UInt32}",
                db_top,
            ),
            top_hosts=self._buckets(
                "SELECT host, count() c FROM {db:Identifier}.creds WHERE host != '' "
                "GROUP BY host ORDER BY c DESC LIMIT {top:UInt32}",
                db_top,
            ),
        )

    def count_host(self, host: str) -> int:
        """Exact count of creds for one host (the enrichment degree)."""
        return int(
            self._c()
            .query(
                "SELECT count() FROM {db:Identifier}.creds WHERE host = {host:String}",
                parameters={"db": self._db, "host": host},
            )
            .result_rows[0][0]
        )

    def search(
        self, *, host: str | None, limit: int, offset: int = 0, exact: bool = False
    ) -> list[CredRow]:
        where = ""
        params: dict[str, object] = {"db": self._db, "lim": int(limit), "off": int(offset)}
        if host and exact:
            where = "WHERE host = {host:String}"  # graph enrichment: exact host
            params["host"] = host
        elif host:
            where = "WHERE host ILIKE {pat:String}"  # dashboard: substring
            params["pat"] = f"%{host}%"
        try:
            rows = self._c().query(
                # `where` is a code constant (not user input); the search term + db + limits
                # are all bound params, so the f-string only splices our own literal.
                "SELECT host,url,login,password,scheme,tld FROM {db:Identifier}.creds "  # noqa: S608
                f"{where} ORDER BY host LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}",
                parameters=params,
            ).result_rows
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.creds table does not exist yet"
                ) from exc
            raise
        return [
            CredRow(host=r[0], url=r[1], login=r[2], password=r[3], scheme=r[4], tld=r[5])
            for r in rows
        ]


@dataclass(frozen=True, slots=True)
class CoverageRow:
    archive_sha256: str
    total_files: int
    parsed_files: int
    unknown_files: int
    pct_parsed: float
    first_seen_at: str  # ISO timestamp


@dataclass(frozen=True, slots=True)
class UnknownRow:
    filename: str
    heuristic_kind: str
    occurrences: int
    archive_count: int
    sample_head: str


@dataclass(frozen=True, slots=True)
class SampleRow:
    archive_sha256: str
    rel_path: str
    size_bytes: int
    sample_head: str


@dataclass(frozen=True, slots=True)
class AuditSearchRow:
    archive_sha256: str
    rel_path: str
    filename: str
    heuristic_kind: str
    size_bytes: int
    match_context: str


@dataclass(frozen=True, slots=True)
class PageEnvelope:
    """Pagination result bundle: the rows for THIS page + the totals the FE
    needs to render "Page M of N". ``total`` and ``page_count`` are always
    populated; they come from a second CH query against a pre-aggregated
    roll-up (cheap even at 10M+ source rows) for /coverage and /unknown, or
    a direct ``count()`` against a skip-indexed WHERE for /samples and /search.
    """

    items: list[object]
    total: int
    page_count: int
    has_more: bool


class FileAuditReader:
    """Read side of the v1.2.6 file_audit observability + v1.2.7 pre-aggregated
    roll-ups. Powers the Corpus Health page.

    Query design (v1.2.7 cut):
      * /coverage and /unknown read from the write-through materialized views
        ``file_audit_per_archive`` and ``file_audit_per_unknown_file``. Source
        row count scales with the audit table (millions), roll-up row count
        scales with distinct groups (typically low-thousands). A GROUP BY over
        the roll-up is 2-4 orders of magnitude cheaper than over file_audit.
      * /samples filters by filename (case-insensitive) with no grouping; the
        ngram skip index + LowCardinality on heuristic_kind make this cheap
        enough without a roll-up. Direct scan.
      * /search is ad-hoc substring across three columns; no pre-materialization
        possible (the predicate is operator-supplied). The ngrambf_v1 skip
        index on sample_head + tokenbf_v1 on rel_path prune granules.
    """

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Client | None = None

    def _c(self) -> Client:
        if self._client is None:
            self._client = get_clickhouse_client()
        return self._client

    def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[object, ...]]:
        try:
            return self._c().query(sql, parameters=params).result_rows
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.file_audit table does not exist yet"
                ) from exc
            raise

    def _scalar(self, sql: str, params: dict[str, object]) -> int:
        rows = self._rows(sql, params)
        return int(rows[0][0]) if rows else 0

    @staticmethod
    def _page_count(total: int, limit: int) -> int:
        if total <= 0:
            return 0
        return (total + limit - 1) // limit

    @staticmethod
    def _window(page: int, limit: int) -> int:
        return max(0, (page - 1) * limit)

    def coverage(
        self, *, page: int, limit: int
    ) -> tuple[list[CoverageRow], int, int]:
        """Returns (rows, total, page_count). Reads the roll-up, not file_audit."""
        off = self._window(page, limit)
        rows = self._rows(
            "SELECT archive_sha256,"
            "       sum(total_files)    AS total_files,"
            "       sum(parsed_files)   AS parsed_files,"
            "       sum(unknown_files)  AS unknown_files,"
            "       round(if(sum(total_files)=0, 0.0,"
            "               100.0 * sum(parsed_files) / sum(total_files)), 2) AS pct_parsed,"
            "       min(first_seen_at)  AS first_seen"
            "  FROM {db:Identifier}.file_audit_per_archive"
            "  GROUP BY archive_sha256"
            "  ORDER BY first_seen DESC"
            "  LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {"db": self._db, "lim": int(limit), "off": int(off)},
        )
        # uniqExact against the roll-up ORDER BY key = cheap read of a small table.
        total = self._scalar(
            "SELECT uniqExact(archive_sha256) FROM {db:Identifier}.file_audit_per_archive",
            {"db": self._db},
        )
        out = [
            CoverageRow(
                archive_sha256=str(r[0]),
                total_files=int(r[1]),
                parsed_files=int(r[2]),
                unknown_files=int(r[3]),
                pct_parsed=float(r[4]),
                first_seen_at=str(r[5]),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    def unknown(
        self, *, page: int, limit: int
    ) -> tuple[list[UnknownRow], int, int]:
        """Returns (rows, total, page_count). Reads the per-unknown-file roll-up."""
        off = self._window(page, limit)
        rows = self._rows(
            "SELECT filename,"
            "       heuristic_kind,"
            "       sum(occurrences)                  AS occurrences,"
            "       uniqExactMerge(archive_count_state) AS archive_count,"
            "       anyMerge(sample_head_state)        AS sample_head"
            "  FROM {db:Identifier}.file_audit_per_unknown_file"
            "  GROUP BY filename, heuristic_kind"
            "  ORDER BY occurrences DESC"
            "  LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {"db": self._db, "lim": int(limit), "off": int(off)},
        )
        total = self._scalar(
            "SELECT uniqExact((filename, heuristic_kind))"
            "  FROM {db:Identifier}.file_audit_per_unknown_file",
            {"db": self._db},
        )
        out = [
            UnknownRow(
                filename=str(r[0]),
                heuristic_kind=str(r[1]),
                occurrences=int(r[2]),
                archive_count=int(r[3]),
                sample_head=str(r[4]),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    def samples(
        self, *, filename: str, page: int, limit: int
    ) -> tuple[list[SampleRow], int, int]:
        """Returns (rows, total, page_count). Filtered scan over file_audit;
        case-insensitive filename match + parsed_at DESC ordering."""
        off = self._window(page, limit)
        rows = self._rows(
            "SELECT archive_sha256, rel_path, size_bytes, sample_head"
            "  FROM {db:Identifier}.file_audit"
            "  WHERE lower(filename) = lower({fn:String})"
            "  ORDER BY parsed_at DESC"
            "  LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {"db": self._db, "fn": filename, "lim": int(limit), "off": int(off)},
        )
        total = self._scalar(
            "SELECT count() FROM {db:Identifier}.file_audit"
            "  WHERE lower(filename) = lower({fn:String})",
            {"db": self._db, "fn": filename},
        )
        out = [
            SampleRow(
                archive_sha256=str(r[0]),
                rel_path=str(r[1]),
                size_bytes=int(r[2]),
                sample_head=str(r[3]),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    def search(
        self, *, q: str, page: int, limit: int
    ) -> tuple[list[AuditSearchRow], int, int]:
        """Returns (rows, total, page_count). Case-insensitive substring across
        filename+rel_path+sample_head. The ngrambf_v1 index on sample_head
        prunes granules that cannot contain the query (case-folded match on
        the lowered column at query time still prunes by ngram presence)."""
        off = self._window(page, limit)
        where = (
            "positionCaseInsensitive(sample_head, {q:String}) > 0"
            " OR positionCaseInsensitive(rel_path, {q:String}) > 0"
            " OR positionCaseInsensitive(filename, {q:String}) > 0"
        )
        rows = self._rows(
            "SELECT archive_sha256, rel_path, filename, heuristic_kind, size_bytes,"
            "       substring(sample_head,"
            "                 greatest(1, positionCaseInsensitive(sample_head, {q:String}) - 80),"
            "                 200) AS match_context"
            f"  FROM {{db:Identifier}}.file_audit"  # noqa: S608
            f"  WHERE {where}"
            "   ORDER BY parsed_at DESC"
            "   LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {"db": self._db, "q": q, "lim": int(limit), "off": int(off)},
        )
        total = self._scalar(
            f"SELECT count() FROM {{db:Identifier}}.file_audit WHERE {where}",  # noqa: S608
            {"db": self._db, "q": q},
        )
        out = [
            AuditSearchRow(
                archive_sha256=str(r[0]),
                rel_path=str(r[1]),
                filename=str(r[2]),
                heuristic_kind=str(r[3]),
                size_bytes=int(r[4]),
                match_context=str(r[5]),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)


__all__ = [
    "AuditSearchRow",
    "Bucket",
    "CoverageRow",
    "CredRow",
    "FileAuditReader",
    "SampleRow",
    "StealerCredsReader",
    "StealerStats",
    "UnknownRow",
]
