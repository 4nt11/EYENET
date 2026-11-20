# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read side of the ULP corpus: stats + credential search.

Reads from ``<db>.extracted_records`` (gotractor's output); the legacy
``<db>.creds`` table is no longer written to and will be dropped once the
transition is confirmed healthy. host / scheme / tld are derived at read
time with ClickHouse's native URL functions (``domain()``, ``protocol()``,
``topLevelDomain()``) so old records (pre derive_url_parts normalize) are
still queryable without a reindex.

Backs the read:stealer API (overview charts + host search). Queries are
parameterized (clickhouse-connect bound params) so the operator's search
term can't inject SQL.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, ClassVar

from eyenet.stealer.clickhouse import (
    clickhouse_db,
    get_async_clickhouse_client,
)

# ClickHouse's error code for "table does not exist". Used to distinguish
# "corpus not initialized yet" (no stealer channels collected from, so
# ensure_schema() has never run) from "CH is unreachable". The former is a
# normal operational state -- empty UI, operator hint -- not a 503.
_CH_UNKNOWN_TABLE = 60


class StealerCorpusUninitializedError(Exception):
    """Raised when a stealer table does not exist yet.

    Semantics: CH is reachable, the DDL just has not been created because
    the stealer-processor has not yet seen a message that triggers
    ``ClickHouseRecordsSink.ensure_schema()`` or ``FileAuditSink.ensure_schema()``.
    The API layer turns this into an empty-but-successful response with an
    ``initialized=False`` marker the dashboard can render as a "add a
    stealer channel" nudge.
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
    """Aggregate + search queries over ``<db>.extracted_records``. Reads
    the credential-emitting families (browser_passwords, windows_credentials,
    firefox_logins, combolist) and derives host / scheme / tld from the
    raw url field via ClickHouse's native URL functions; the derive_url_parts
    normalize verb pre-computes the same at write time, so sargable queries
    on new emits can use ``fields['host']`` directly.

    Async: uses clickhouse-connect's AsyncClient so parallel /v1/stealer
    requests do not fight over a shared sync client."""

    # Families whose records carry a (url, login, password) triple that
    # fits the credential-search surface. Listed as a ClassVar so the
    # closed set is one place to edit when a new credential-emitting
    # family lands.
    _CRED_FAMILIES: ClassVar[list[str]] = [
        "browser_passwords",
        "windows_credentials",
        "firefox_logins",
        "combolist",
    ]
    # Derive host/scheme/tld with ClickHouse URL functions. We canonicalise
    # BOTH fields['url'] and fields['host'] because some rules capture a
    # raw URL into the "host" field pre derive_url_parts (e.g.
    # passwords_block_title), and feeding that straight into the display
    # yielded entries like 'https://accounts.google.com/' in the
    # distribution charts. coalesce picks the first non-empty derivation.
    # New records written post-derive_url_parts land with fields['host']
    # already registrable and bypass this pathway via the first branch.
    _HOST_EXPR: ClassVar[str] = (
        "lower(coalesce("
        "nullIf(domain(fields['url']), ''), "
        "nullIf(domain(fields['host']), ''), "
        "nullIf(fields['host'], ''), ''))"
    )
    _SCHEME_EXPR: ClassVar[str] = (
        "lower(coalesce(nullIf(fields['scheme'], ''), nullIf(protocol(fields['url']), ''), ''))"
    )
    _TLD_EXPR: ClassVar[str] = (
        "coalesce("
        "nullIf(fields['tld'], ''), "
        "nullIf(topLevelDomain(fields['url']), ''), "
        "nullIf(topLevelDomain(fields['host']), ''), '')"
    )
    _WHERE_ANY_URL: ClassVar[str] = (
        "family IN {fams:Array(String)} AND (notEmpty(fields['url']) OR notEmpty(fields['host']))"
    )

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    async def _c(self) -> Any:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = await get_async_clickhouse_client()
        return self._client

    async def _buckets(self, sql: str, params: dict[str, object]) -> list[Bucket]:
        client = await self._c()
        result = await client.query(sql, parameters=params)
        return [Bucket(key=str(r[0]), count=int(r[1])) for r in result.result_rows]

    async def stats(self, *, top: int = 20) -> StealerStats:
        """Overview stats for the /v1/stealer/stats endpoint.

        v1.3.1: reads from the stats_rollup_* AggregatingMergeTree tables
        populated on every extracted_records INSERT. Before: 4 FULL scans
        of extracted_records with FINAL + uniqExact (O(N)). After: one
        single-row read + three small GROUP BY/ORDER BY/LIMIT scans over
        pre-aggregated rollup tables (O(1)-ish regardless of corpus size).
        unique_creds + distinct_hosts are HLL approximations (~1% error).
        """
        top_param: dict[str, object] = {"top": int(top)}
        try:
            client = await self._c()
            # self._db is operator config, not user input; no injection risk.
            # v1.3.1: total_creds is now AggregateFunction(uniqExact, identity),
            # so uniqExactMerge instead of sum. Reindex-safe by construction.
            sql_totals = (
                "SELECT uniqExactMerge(total_creds), uniqMerge(unique_creds),"  # noqa: S608
                f" uniqMerge(distinct_hosts) FROM {self._db}.stats_rollup_totals"  # nosec B608
            )
            result = await client.query(sql_totals)
            scalars = result.result_rows[0]
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.extracted_records table does not exist yet"
                ) from exc
            raise
        by_scheme, by_tld, top_hosts = await asyncio.gather(
            self._buckets(
                f"SELECT scheme, uniqExactMerge(cnt) c "  # noqa: S608  # nosec B608
                f"FROM {self._db}.stats_rollup_scheme "
                "GROUP BY scheme ORDER BY c DESC",
                {},
            ),
            self._buckets(
                f"SELECT tld, uniqExactMerge(cnt) c "  # noqa: S608  # nosec B608
                f"FROM {self._db}.stats_rollup_tld "
                "GROUP BY tld ORDER BY c DESC LIMIT {top:UInt32}",
                top_param,
            ),
            self._buckets(
                f"SELECT host, uniqExactMerge(cnt) c "  # noqa: S608  # nosec B608
                f"FROM {self._db}.stats_rollup_host "
                "GROUP BY host ORDER BY c DESC LIMIT {top:UInt32}",
                top_param,
            ),
        )
        return StealerStats(
            total_creds=int(scalars[0]),
            unique_creds=int(scalars[1]),
            distinct_hosts=int(scalars[2]),
            by_scheme=by_scheme,
            by_tld=by_tld,
            top_hosts=top_hosts,
        )

    async def count_host(self, host: str) -> int:
        """Exact count of UNIQUE creds for one host (the enrichment degree)."""
        # v1.3.4.4: dropped FINAL (31s on prod) in favour of countDistinct
        # over the identity tuple (0.5s). FINAL collapsed reindex copies in
        # memory across every part; countDistinct does the same dedup on
        # the filtered subset only. Same dedup grain as search's DISTINCT.
        client = await self._c()
        host_expr = self._HOST_EXPR
        result = await client.query(
            "SELECT countDistinct("  # noqa: S608
            f"({host_expr}, fields['url'], fields['login'], fields['password'])) "
            f"FROM {self._db}.extracted_records "  # nosec B608
            f"WHERE {self._WHERE_ANY_URL} AND {host_expr} = {{host:String}}",
            parameters={"fams": self._CRED_FAMILIES, "host": host},
        )
        return int(result.result_rows[0][0])

    async def search(
        self, *, host: str | None, limit: int, offset: int = 0, exact: bool = False
    ) -> list[CredRow]:
        host_expr = self._HOST_EXPR
        scheme_expr = self._SCHEME_EXPR
        tld_expr = self._TLD_EXPR
        host_filter = ""
        params: dict[str, object] = {
            "fams": self._CRED_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        if host and exact:
            host_filter = f" AND {host_expr} = {{host:String}}"
            params["host"] = host
        elif host:
            host_filter = f" AND {host_expr} ILIKE {{pat:String}}"
            params["pat"] = f"%{host}%"
        try:
            client = await self._c()
            # v1.3.4.4: dropped FINAL. extracted_records is 100M rows x 11
            # parts of ReplacingMergeTree; FINAL merged across all parts in
            # memory to collapse reindex duplicates and took 58s on prod
            # for a 200-row page. Without FINAL the same query is 750ms.
            # DISTINCT replaces FINAL's dedup for the paged result: a
            # cred's (host, url, login, password) tuple is identical across
            # all reindex copies (by the identity tuple DDL), so DISTINCT
            # post-filter returns at most one row per unique cred, which is
            # what the operator sees.
            result = await client.query(
                f"SELECT DISTINCT {host_expr} h, fields['url'] u, fields['login'] l, "  # noqa: S608  # nosec B608
                f"       fields['password'] p, {scheme_expr} s, {tld_expr} t "
                f"FROM {self._db}.extracted_records "
                f"WHERE {self._WHERE_ANY_URL}{host_filter} "
                "ORDER BY h LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
            rows = result.result_rows
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.extracted_records table does not exist yet"
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
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    async def _c(self) -> Any:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = await get_async_clickhouse_client()
        return self._client

    async def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[Any, ...]]:
        try:
            client = await self._c()
            result = await client.query(sql, parameters=params)
            return result.result_rows  # type: ignore[no-any-return]
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.file_audit table does not exist yet"
                ) from exc
            raise

    async def _scalar(self, sql: str, params: dict[str, object]) -> int:
        rows = await self._rows(sql, params)
        return int(rows[0][0]) if rows else 0

    @staticmethod
    def _page_count(total: int, limit: int) -> int:
        if total <= 0:
            return 0
        return (total + limit - 1) // limit

    @staticmethod
    def _window(page: int, limit: int) -> int:
        return max(0, (page - 1) * limit)

    async def coverage(self, *, page: int, limit: int) -> tuple[list[CoverageRow], int, int]:
        """Returns (rows, total, page_count). Reads the roll-up, not file_audit."""
        off = self._window(page, limit)
        rows, total = await asyncio.gather(
            self._rows(
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
            ),
            # uniqExact against the roll-up ORDER BY key: cheap read of a small table.
            self._scalar(
                "SELECT uniqExact(archive_sha256) FROM {db:Identifier}.file_audit_per_archive",
                {"db": self._db},
            ),
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

    async def unknown(self, *, page: int, limit: int) -> tuple[list[UnknownRow], int, int]:
        """Returns (rows, total, page_count). Reads the per-unknown-file roll-up."""
        off = self._window(page, limit)
        rows, total = await asyncio.gather(
            self._rows(
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
            ),
            self._scalar(
                "SELECT uniqExact((filename, heuristic_kind))"
                "  FROM {db:Identifier}.file_audit_per_unknown_file",
                {"db": self._db},
            ),
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

    async def samples(
        self, *, filename: str, page: int, limit: int
    ) -> tuple[list[SampleRow], int, int]:
        """Returns (rows, total, page_count). Filtered scan over file_audit;
        case-insensitive filename match + parsed_at DESC ordering."""
        off = self._window(page, limit)
        rows, total = await asyncio.gather(
            self._rows(
                "SELECT archive_sha256, rel_path, size_bytes, sample_head"
                "  FROM {db:Identifier}.file_audit"
                "  WHERE lower(filename) = lower({fn:String})"
                "  ORDER BY parsed_at DESC"
                "  LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                {"db": self._db, "fn": filename, "lim": int(limit), "off": int(off)},
            ),
            self._scalar(
                "SELECT count() FROM {db:Identifier}.file_audit"
                "  WHERE lower(filename) = lower({fn:String})",
                {"db": self._db, "fn": filename},
            ),
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

    async def search(
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
        rows, total = await asyncio.gather(
            self._rows(
                "SELECT archive_sha256, rel_path, filename, heuristic_kind, size_bytes,"  # nosec B608  # noqa: S608
                "       substring(sample_head,"
                "                 greatest(1, positionCaseInsensitive("
                "                                   sample_head, {q:String}) - 80),"
                "                 200) AS match_context"
                f"  FROM {{db:Identifier}}.file_audit"
                f"  WHERE {where}"
                "   ORDER BY parsed_at DESC"
                "   LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                {"db": self._db, "q": q, "lim": int(limit), "off": int(off)},
            ),
            self._scalar(
                f"SELECT count() FROM {{db:Identifier}}.file_audit WHERE {where}",  # noqa: S608  # nosec B608
                {"db": self._db, "q": q},
            ),
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


# v1.3.3 per-victim artifact reader. Backs the FE drawer.
#
# Query design:
#   - list_cards() reads victim_profiles directly (AggregatingMergeTree with
#     SAF fields - no FINAL needed because all aggregates are commutative
#     under merge). Filters are indexed via the set skip indexes on country,
#     traffic_affid, has_wallet, has_corporate_marker.
#   - detail() reads one row of victim_profiles plus joins against the
#     mitre_catalog YAML (loaded once, cached) to render ATT&CK technique
#     badges. Joins are in Python because the catalog is a small YAML file,
#     not a CH table.
#   - file_tree() reads from file_audit (the materialized victim_folder
#     column has a set skip index for free).
#   - records() reads from extracted_records with (archive_sha256,
#     victim_folder) filter. Victim_folder derivation from file_path at
#     query time because the stored column is broken (pipeline fix pending).
#   - domains() reads from victim_domains ordered by (domain, archive,
#     victim) so the (archive, victim) filter scans contiguous granules.


@dataclass(frozen=True, slots=True)
class ArtifactCardRow:
    archive_sha256: str
    victim_folder: str
    country: str
    traffic_affid: str
    build_version: str
    creds_count: int
    cookies_count: int
    wallet_vaults_count: int
    has_corporate_marker: bool
    has_wallet: bool
    has_crypter_banner: bool


@dataclass(frozen=True, slots=True)
class ArtifactDetailRow:
    archive_sha256: str
    victim_folder: str
    source: str
    country: str
    egress_ip: str
    user_name: str
    computer_name: str
    os_version: str
    traffic_affid: str
    build_version: str
    payload_md5: str
    work_dir: str
    creds_count: int
    cookies_count: int
    autofills_count: int
    history_count: int
    downloads_count: int
    processes_count: int
    software_count: int
    discord_tokens_count: int
    steam_tokens_count: int
    google_refresh_count: int
    localstorage_jwt_count: int
    wallet_vaults_count: int
    has_corporate_marker: bool
    has_webmail_leak: bool
    has_wallet: bool
    has_crypter_banner: bool
    webmail_identity: str
    first_corporate_marker: str
    first_wallet_family: str
    fired_rule_ids: list[str] = field(default_factory=list)
    # v1.3.4 monitored-domain hits. Count of distinct domains this victim
    # touched that match the operator's monitored_domains watchlist via
    # exact or suffix match. Drives the 'DOMAIN HITS' stat tile.
    monitored_domain_hits: int = 0
    # v1.3.6 per-victim parse coverage. Read from file_audit_per_victim:
    # total_files = how many files ride under this victim folder, parsed =
    # how many at least one rule's path_glob touched, pct = ratio. Drives
    # the "COVERAGE" stat tile on the drawer header.
    coverage_total_files: int = 0
    coverage_parsed_files: int = 0
    coverage_pct: float = 0.0
    # v1.3.8 stealer-family verdict. Written by the classifier
    # (eyenet.stealer.classifier) at pipeline-end and/or by the
    # stealer-reclassify CLI. All four fields are populated together:
    # when no confident verdict exists, slug is empty and confidence
    # is 0.0. runners_up is a list of (slug, confidence) pairs so the
    # drawer evidence popover can show the scorer's state of mind.
    family_slug: str = ""
    family_confidence: float = 0.0
    family_evidence: list[str] = field(default_factory=list)
    family_runners_up: list[tuple[str, float]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ArtifactFileRow:
    rel_path: str
    filename: str
    size_bytes: int
    heuristic_kind: str
    extractor_touched: bool
    rows_emitted: int
    sample_head: str
    file_sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactRecordRow:
    rule_id: str
    family: str
    file_path: str
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class ArtifactDomainRow:
    domain: str
    source_kind: str
    count: int


class StealerArtifactsReader:
    """Read side of the per-victim artifact drawer. Async: wraps clickhouse-connect's
    AsyncClient so three parallel API calls (detail + files + domains) don't fight
    over a shared sync client the way the legacy readers did."""

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    async def _c(self) -> Any:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = await get_async_clickhouse_client()
        return self._client

    async def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[Any, ...]]:
        try:
            client = await self._c()
            result = await client.query(sql, parameters=params)
            return result.result_rows  # type: ignore[no-any-return]
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.victim_profiles table does not exist yet"
                ) from exc
            raise

    @staticmethod
    def _page_count(total: int, limit: int) -> int:
        return (total + limit - 1) // limit if total else 0

    async def list_cards(
        self,
        *,
        page: int,
        limit: int,
        country: str | None = None,
        traffic_affid: str | None = None,
        has_wallet: bool | None = None,
        has_corporate: bool | None = None,
        family: str | None = None,
    ) -> tuple[list[ArtifactCardRow], int, int]:
        # v1.3.4.3: read from victim_counts (ReplacingMergeTree with plain
        # UInt64 counts, refreshed every 5 min from victim_profiles). The
        # heavy uniqExactState materialization happens ONCE per refresh
        # cycle in background, not on every API call. FINAL collapses
        # overlapping refresh generations keyed on refreshed_at; the table
        # is ~20k rows so FINAL is sub-second. Counts are up to 5 min stale,
        # acceptable for an operator UI.
        where = ["1"]
        params: dict[str, object] = {}
        if country:
            where.append("country = {country:String}")
            params["country"] = country
        if traffic_affid:
            where.append("traffic_affid = {affid:String}")
            params["affid"] = traffic_affid
        if has_wallet is not None:
            where.append("has_wallet = {hw:UInt8}")
            params["hw"] = 1 if has_wallet else 0
        if has_corporate is not None:
            where.append("has_corporate_marker = {hc:UInt8}")
            params["hc"] = 1 if has_corporate else 0
        family_join = ""
        if family:
            family_join = (
                " AND (archive_sha256, victim_folder) IN ("  # noqa: S608  # nosec B608
                f"SELECT archive_sha256, victim_folder FROM {self._db}.victim_family_verdict FINAL "
                " WHERE slug = {family_slug:String})"
            )
            params["family_slug"] = family

        where_sql = " AND ".join(where) + family_join
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        total_rows = await self._rows(
            f"SELECT count() FROM {self._db}.victim_counts FINAL WHERE {where_sql}",  # nosec B608  # noqa: S608
            params,
        )
        total = int(total_rows[0][0]) if total_rows else 0

        rows = await self._rows(
            "SELECT "  # noqa: S608
            "  archive_sha256, victim_folder, country, traffic_affid, build_version, "
            "  creds_count, cookies_count, wallet_vaults_count, "
            "  has_corporate_marker, has_wallet, has_crypter_banner "
            f"FROM {self._db}.victim_counts FINAL "  # nosec B608
            f"WHERE {where_sql} "
            "ORDER BY archive_sha256, victim_folder "
            "LIMIT {limit:UInt32} OFFSET {offset:UInt32}",
            params,
        )
        out = [
            ArtifactCardRow(
                archive_sha256=r[0],
                victim_folder=r[1],
                country=r[2],
                traffic_affid=r[3],
                build_version=r[4],
                creds_count=int(r[5]),
                cookies_count=int(r[6]),
                wallet_vaults_count=int(r[7]),
                has_corporate_marker=bool(r[8]),
                has_wallet=bool(r[9]),
                has_crypter_banner=bool(r[10]),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    async def detail(self, archive_sha256: str, victim_folder: str) -> ArtifactDetailRow | None:
        # v1.3.4.3: read from victim_counts (see list_cards docstring).
        rows = await self._rows(
            "SELECT "  # noqa: S608
            "  source, country, egress_ip, user_name, computer_name, os_version, "
            "  traffic_affid, build_version, payload_md5, work_dir, "
            "  creds_count, cookies_count, autofills_count, history_count, "
            "  downloads_count, processes_count, software_count, "
            "  discord_tokens_count, steam_tokens_count, google_refresh_count, "
            "  localstorage_jwt_count, wallet_vaults_count, "
            "  has_corporate_marker, has_webmail_leak, has_wallet, has_crypter_banner, "
            "  webmail_identity, first_corporate_marker, first_wallet_family "
            f"FROM {self._db}.victim_counts FINAL "  # nosec B608
            "WHERE archive_sha256 = {sha:FixedString(64)} "
            "  AND victim_folder = {vf:String} "
            "LIMIT 1",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        if not rows:
            return None
        r = rows[0]
        # Pull the distinct rule_ids fired for this victim + the monitored
        # domain hits in parallel; both are independent per-victim scans
        # over the same ClickHouse pool connection.
        fired, hits, coverage, verdict = await asyncio.gather(
            self._rows(
                # v1.3.1: tiny-table lookup off extracted_rules_per_victim
                # keyed on (archive, victim_folder, rule_id). Was a full
                # scan of extracted_records with splitByChar in WHERE.
                "SELECT DISTINCT rule_id "  # noqa: S608
                f"FROM {self._db}.extracted_rules_per_victim "  # nosec B608
                "WHERE archive_sha256 = {sha:FixedString(64)} "
                "  AND victim_folder  = {vf:String}",
                {"sha": archive_sha256, "vf": victim_folder},
            ),
            self._monitored_domain_hits(archive_sha256, victim_folder),
            self._coverage(archive_sha256, victim_folder),
            self._family_verdict(archive_sha256, victim_folder),
        )
        return ArtifactDetailRow(
            archive_sha256=archive_sha256,
            victim_folder=victim_folder,
            source=r[0],
            country=r[1],
            egress_ip=r[2],
            user_name=r[3],
            computer_name=r[4],
            os_version=r[5],
            traffic_affid=r[6],
            build_version=r[7],
            payload_md5=r[8],
            work_dir=r[9],
            creds_count=int(r[10]),
            cookies_count=int(r[11]),
            autofills_count=int(r[12]),
            history_count=int(r[13]),
            downloads_count=int(r[14]),
            processes_count=int(r[15]),
            software_count=int(r[16]),
            discord_tokens_count=int(r[17]),
            steam_tokens_count=int(r[18]),
            google_refresh_count=int(r[19]),
            localstorage_jwt_count=int(r[20]),
            wallet_vaults_count=int(r[21]),
            has_corporate_marker=bool(r[22]),
            has_webmail_leak=bool(r[23]),
            has_wallet=bool(r[24]),
            has_crypter_banner=bool(r[25]),
            webmail_identity=r[26],
            first_corporate_marker=r[27],
            first_wallet_family=r[28],
            fired_rule_ids=[row[0] for row in fired],
            monitored_domain_hits=hits,
            coverage_total_files=coverage[0],
            coverage_parsed_files=coverage[1],
            coverage_pct=coverage[2],
            family_slug=verdict[0],
            family_confidence=verdict[1],
            family_evidence=verdict[2],
            family_runners_up=verdict[3],
        )

    async def _coverage(self, archive_sha256: str, victim_folder: str) -> tuple[int, int, float]:
        """Live per-victim coverage computed from file_audit JOIN
        extracted_records. We deliberately bypass file_audit_per_victim:
        its parsed_files column is set from file_audit.extractor_touched,
        which only tracks ulpextract's pw_files set (Passwords.txt variants)
        and does not see gotractor's emissions on InstalledSoftware.txt,
        ProcessList.txt, cookies.txt, etc. The MV also summed raw row
        counts, double-counting rel_path dupes from reindex passes.

        Definition: total = uniqExact(filename) over non-empty / non-binary
        file_audit rows in this (archive, victim). parsed = same uniqExact
        but filtered to filenames whose rel_path appears at least once in
        extracted_records for the same (archive, victim). Matches the
        Files-tab dedup-by-filename view so the tile and the tree agree."""
        # v1.3.1: LEFT JOIN against a per-archive slice of
        # extracted_rows_per_file (direct index seek on the sort key
        # (archive, file_path)) instead of a full-scan count+group by
        # over extracted_records.
        rows = await self._rows(
            "SELECT "  # noqa: S608
            "  uniqExact(fa.filename) AS total, "
            "  uniqExactIf(fa.filename, erf.n > 0) AS parsed, "
            "  round(if(uniqExact(fa.filename) = 0, 0.0, "
            "    100.0 * uniqExactIf(fa.filename, erf.n > 0) "
            "    / uniqExact(fa.filename)), 1) AS pct "
            f"FROM {self._db}.file_audit AS fa "  # nosec B608
            "LEFT JOIN ("
            "  SELECT file_path, uniqExactMerge(cnt) AS n "
            f"  FROM {self._db}.extracted_rows_per_file "  # nosec B608
            "  WHERE archive_sha256 = {sha:FixedString(64)} "
            "  GROUP BY file_path"
            ") AS erf ON erf.file_path = fa.rel_path "
            "WHERE fa.archive_sha256 = {sha:FixedString(64)} "
            "  AND fa.victim_folder = {vf:String} "
            "  AND fa.heuristic_kind NOT IN ('empty','binary')",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        if not rows:
            return (0, 0, 0.0)
        r = rows[0]
        return (int(r[0] or 0), int(r[1] or 0), float(r[2] or 0.0))

    async def _family_verdict(
        self, archive_sha256: str, victim_folder: str
    ) -> tuple[str, float, list[str], list[tuple[str, float]]]:
        """Read the per-victim stealer-family verdict. Returns
        (slug, confidence, evidence, runners_up). Empty slug means no
        verdict row yet (classifier has not run for this victim)."""
        try:
            rows = await self._rows(
                "SELECT slug, confidence, evidence, runners_up "  # noqa: S608
                f"FROM {self._db}.victim_family_verdict FINAL "  # nosec B608
                "WHERE archive_sha256 = {sha:FixedString(64)} "
                "  AND victim_folder = {vf:String} "
                "LIMIT 1",
                {"sha": archive_sha256, "vf": victim_folder},
            )
        except StealerCorpusUninitializedError:
            # verdict table is lazy: a fresh host without a classify pass
            # reads as "no verdict yet" instead of 503.
            return ("", 0.0, [], [])
        if not rows:
            return ("", 0.0, [], [])
        r = rows[0]
        evidence = [str(x) for x in (r[2] or [])]
        runners = [(str(s), float(c)) for s, c in (r[3] or [])]
        return (str(r[0] or ""), float(r[1] or 0.0), evidence, runners)

    async def _monitored_domain_hits(self, archive_sha256: str, victim_folder: str) -> int:
        """Count distinct monitored-watchlist domains this victim touched.

        Joins ``victim_domains`` against ``monitored_domains`` by exact or
        suffix match depending on each row's ``match_type``. Returns 0 if
        the monitored_domains table has no rows (watchlist not seeded yet),
        which is the common early-stage state.

        Split as a UNION ALL of two joins (one per match_type) because
        ClickHouse 24.x rejects OR-ed conditions mixing columns from both
        sides of a JOIN unless ``allow_experimental_join_condition=1``.
        The suffix arm is an implicit cross join filtered by ``endsWith`` --
        fine while monitored_domains stays small (dozens to low thousands);
        if the watchlist ever grows into the millions, revisit this.
        """
        rows = await self._rows(
            "SELECT uniqExact(domain) AS n FROM ("  # noqa: S608
            "  SELECT vd.domain "
            f"  FROM {self._db}.victim_domains AS vd "  # nosec B608
            f"  INNER JOIN {self._db}.monitored_domains AS md "
            "    ON vd.domain = md.domain "
            "  WHERE md.match_type = 'exact' "
            "    AND vd.archive_sha256 = {sha:FixedString(64)} "
            "    AND vd.victim_folder  = {vf:String} "
            "  UNION ALL "
            "  SELECT vd.domain "
            f"  FROM {self._db}.victim_domains AS vd, "  # nosec B608
            f"       {self._db}.monitored_domains AS md "
            "  WHERE md.match_type = 'suffix' "
            "    AND endsWith(vd.domain, md.domain) "
            "    AND vd.archive_sha256 = {sha:FixedString(64)} "
            "    AND vd.victim_folder  = {vf:String} "
            ")",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        return int(rows[0][0]) if rows else 0

    async def file_tree(self, archive_sha256: str, victim_folder: str) -> list[ArtifactFileRow]:
        # v1.3.1: LEFT JOIN against a per-archive slice of
        # extracted_rows_per_file (direct index seek on (archive,
        # file_path)) instead of a full scan+group-by over
        # extracted_records. extractor_touched still OR'd in so the
        # legacy ulpextract pre-pass flag still contributes.
        rows = await self._rows(
            "SELECT fa.rel_path, fa.filename, fa.size_bytes, fa.heuristic_kind, "  # noqa: S608
            "       (coalesce(erf.n, 0) > 0) OR fa.extractor_touched AS touched, "
            "       coalesce(erf.n, 0)                                AS rows_emitted, "
            "       fa.sample_head, fa.file_sha256 "
            f"FROM {self._db}.file_audit AS fa "  # nosec B608
            "LEFT JOIN ("
            "  SELECT file_path, uniqExactMerge(cnt) AS n "
            f"  FROM {self._db}.extracted_rows_per_file "  # nosec B608
            "  WHERE archive_sha256 = {sha:FixedString(64)} "
            "  GROUP BY file_path"
            ") AS erf ON erf.file_path = fa.rel_path "
            "WHERE fa.archive_sha256 = {sha:FixedString(64)} "
            "  AND fa.victim_folder = {vf:String} "
            "ORDER BY fa.rel_path",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        return [
            ArtifactFileRow(
                rel_path=r[0],
                filename=r[1],
                size_bytes=int(r[2]),
                heuristic_kind=r[3],
                extractor_touched=bool(r[4]),
                rows_emitted=int(r[5]),
                sample_head=r[6],
                file_sha256=r[7],
            )
            for r in rows
        ]

    # Drawer tab -> set of rule_ids. Single source of truth so the FE
    # does not need to know the rule-id catalog. "credentials" / "cookies"
    # / "system" match the drawer tab ids; add new categories here as the
    # rule library grows.
    RECORD_CATEGORIES: ClassVar[dict[str, list[str]]] = {
        "credentials": [
            "passwords_block_title",
            "passwords_block_divider",
            "passwords_block_browser",
            "passwords_block_upper",
            "credentials_windows",
            "firefox_logins_json",
        ],
        # Brute-force wordlist candidates (one field: candidate). Not
        # credentials in the usual (host, user, password) sense; belongs
        # to its own tab/view so the Credentials tab does not get
        # 1000+ junk rows that render as blanks.
        "wordlist": [
            "brute_wordlist",
        ],
        "cookies": [
            "netscape_cookies",
            "cookies_netscape_tsv",
        ],
        # System = canonical machine-profile records. The FE coalesces
        # these into one host.* / av.* / build.* / net.* snapshot via
        # stealerCanonicalFields.js; the Python side only picks the
        # rule_ids that emit profile data (not software lists, not
        # process lists, those live under their own categories).
        "system": [
            "environment_windows",
            "stealer_info_yaml",
            "information_v29_shape",
            "software_corporate_marker",
        ],
        "software": [
            "software_installed_list",
        ],
        "processes": [
            "processes_dash_pid",
            "processes_plain_exe",
        ],
    }

    async def records(
        self,
        archive_sha256: str,
        victim_folder: str,
        *,
        page: int,
        limit: int,
        rule_id: str | None = None,
        family: str | None = None,
        category: str | None = None,
    ) -> tuple[list[ArtifactRecordRow], int, int]:
        # v1.3.1: read from extracted_records_by_victim, sorted on
        # (archive, victim_folder, rule_id, file_path). Before: filter via
        # splitByChar scanned the archive's whole slice; ~1s per query,
        # 2s total under parallel count+page fan-out. After: index seek.
        where = [
            "archive_sha256 = {sha:FixedString(64)}",
            "victim_folder = {vf:String}",
        ]
        params: dict[str, object] = {"sha": archive_sha256, "vf": victim_folder}
        if rule_id:
            where.append("rule_id = {rid:String}")
            params["rid"] = rule_id
        if family:
            where.append("family = {fam:String}")
            params["fam"] = family
        if category:
            ids = self.RECORD_CATEGORIES.get(category, [])
            if not ids:
                return ([], 0, 0)
            where.append("rule_id IN {rids:Array(String)}")
            params["rids"] = ids
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset
        where_sql = " AND ".join(where)

        total_rows, rows = await asyncio.gather(
            self._rows(
                f"SELECT count() FROM {self._db}.extracted_records_by_victim WHERE {where_sql}",  # nosec B608  # noqa: S608
                params,
            ),
            self._rows(
                "SELECT rule_id, family, file_path, fields "  # noqa: S608
                f"FROM {self._db}.extracted_records_by_victim "  # nosec B608
                f"WHERE {where_sql} "
                "ORDER BY rule_id, file_path "
                "LIMIT {limit:UInt32} OFFSET {offset:UInt32}",
                params,
            ),
        )
        total = int(total_rows[0][0]) if total_rows else 0
        out = [
            ArtifactRecordRow(
                rule_id=r[0],
                family=r[1],
                file_path=r[2],
                fields={str(k): str(v) for k, v in (r[3] or {}).items()},
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    async def domains(self, archive_sha256: str, victim_folder: str) -> list[ArtifactDomainRow]:
        rows = await self._rows(
            "SELECT domain, source_kind, sum(count) AS total_count "  # noqa: S608
            f"FROM {self._db}.victim_domains "  # nosec B608
            "WHERE archive_sha256 = {sha:FixedString(64)} "
            "  AND victim_folder = {vf:String} "
            "GROUP BY domain, source_kind "
            "ORDER BY total_count DESC, domain",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        return [ArtifactDomainRow(domain=r[0], source_kind=r[1], count=int(r[2])) for r in rows]


@dataclass(frozen=True, slots=True)
class ParseFailureStats:
    """Corpus-wide tiles for the parse-failures workbench header.

    total_files/parsed_files come from the per-victim roll-up MV so the
    cost is O(victims), not O(files). fail_files + shape_buckets come
    from the same LEFT JOIN the shape list uses, with no WHERE filters
    beyond the parse-failure predicate itself.

    "fail_files" here means "extractor touched the file and 0 records
    came out", not distinct from gotractor crashing on the file. The
    pipeline does not currently carry a hard-error flag; add a
    file_audit.parse_error column when that distinction matters."""

    total_files: int
    parsed_files: int
    coverage_pct: float
    fail_files: int
    shape_buckets: int
    crash_files: int  # parse_error != '' in file_audit (gotractor panicked)


@dataclass(frozen=True, slots=True)
class ParseFailureShape:
    """One shape bucket for the parse-failures workbench.

    A shape bucket groups files whose sample_head collapses to the same
    character-class fingerprint. count/victims/archives/files are
    uniqExact over the file_audit rows that fell into this shape; sample
    is one representative sample_head; filenames is the top-N filenames
    seen under this shape so the operator can see "these are the
    Passwords.txt-looking files we aren't parsing"."""

    shape_sig: str
    shape_preview: str
    count: int
    victims: int
    archives: int
    sample: str
    sample_archive_sha256: str
    sample_victim_folder: str
    sample_file_path: str
    heuristic_kind: str
    filenames: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ParseFailureSample:
    """One raw sample row inside a shape bucket."""

    archive_sha256: str
    victim_folder: str
    file_path: str
    filename: str
    size_bytes: int
    sample_head: str
    heuristic_kind: str


class StealerFailuresReader:
    """Read side of the parse-failures workbench (file-level).

    A "parse failure" at the file granularity is a file that at least one
    rule's path_glob touched (extractor_touched=1) but for which no
    gotractor records were ever emitted. We detect those via a LEFT JOIN
    against extracted_records keyed on file_path.

    Shape fingerprint: compute from sample_head in SQL via a stacked
    replaceRegexpAll (letters -> A, digits -> 9, whitespace -> _,
    everything else literal), truncated to the first 200 chars so the
    shape key stays stable under tail-noise drift. GROUP BY that sig
    yields the bucketed workbench view."""

    # Character-class signature expression. Applied to a truncated
    # sample_head. Lowercase first so Soft vs soft collapse into the
    # same shape.
    _SIG_EXPR = (
        "lower("
        "replaceRegexpAll("
        "replaceRegexpAll("
        "replaceRegexpAll("
        "substring(fa.sample_head, 1, 200), "
        "'[A-Za-z]+', 'A'), "
        "'[0-9]+', '9'), "
        "'\\\\s+', '_'))"
    )

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()

    async def _c(self) -> Any:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = await get_async_clickhouse_client()
        return self._client

    async def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[Any, ...]]:
        try:
            client = await self._c()
            result = await client.query(sql, parameters=params)
            return result.result_rows  # type: ignore[no-any-return]
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.file_audit table does not exist yet"
                ) from exc
            raise

    @staticmethod
    def _page_count(total: int, limit: int) -> int:
        return (total + limit - 1) // limit if total else 0

    async def list_shapes(
        self,
        *,
        page: int,
        limit: int,
        filename: str | None = None,
        heuristic_kind: str | None = None,
    ) -> tuple[list[ParseFailureShape], int, int]:
        """Grouped by shape, ORDER BY count DESC. One row per distinct shape
        fingerprint. Optional filters narrow the base failure set before
        grouping (the operator can drill by filename substring or
        heuristic_kind to focus on text files, config files, etc)."""
        where = [
            "fa.victim_folder != ''",
            "fa.heuristic_kind NOT IN ('empty','binary')",
            "er.n = 0",
        ]
        params: dict[str, object] = {}
        if filename:
            where.append("positionCaseInsensitive(fa.filename, {fn:String}) > 0")
            params["fn"] = filename
        if heuristic_kind:
            where.append("fa.heuristic_kind = {hk:String}")
            params["hk"] = heuristic_kind
        where_sql = " AND ".join(where)
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        # v1.3.1: replace the FULL scan of extracted_records (3.6M rows FINAL
        # GROUP BY file_path, 4s wall on prod) with an anti-join against the
        # extracted_file_paths MV (one row per distinct file_path, maintained
        # on insert). Drop FINAL on file_audit: shape stats are tolerant of
        # the tiny dup window before a ReplacingMergeTree merge finishes.
        # self._db is operator config, not user input; no injection risk.
        where = [w for w in where if w != "er.n = 0"]
        where.append(
            f"fa.rel_path NOT IN (SELECT file_path FROM {self._db}.extracted_file_paths)"  # noqa: S608  # nosec B608
        )
        where_sql = " AND ".join(where)
        base_from = f"FROM {self._db}.file_audit AS fa "  # nosec B608

        total_rows = await self._rows(
            f"SELECT uniqExact({self._SIG_EXPR}) {base_from} WHERE {where_sql}",
            params,
        )
        total = int(total_rows[0][0]) if total_rows else 0

        rows = await self._rows(
            f"SELECT "
            f"  {self._SIG_EXPR}                        AS sig, "
            "  any(substring(fa.sample_head, 1, 200)) AS preview, "
            "  count()                                AS n_files, "
            "  uniqExact((fa.archive_sha256, fa.victim_folder)) AS n_victims, "
            "  uniqExact(fa.archive_sha256)           AS n_archives, "
            "  any(fa.sample_head)                    AS sample, "
            "  any(fa.archive_sha256)                 AS sample_sha, "
            "  any(fa.victim_folder)                  AS sample_vf, "
            "  any(fa.rel_path)                       AS sample_path, "
            "  any(fa.heuristic_kind)                 AS sample_hk, "
            "  groupUniqArray(10)(fa.filename)        AS filenames "
            f"{base_from} "
            f"WHERE {where_sql} "
            "GROUP BY sig "
            "ORDER BY n_files DESC "
            "LIMIT {limit:UInt32} OFFSET {offset:UInt32}",
            params,
        )
        out = [
            ParseFailureShape(
                shape_sig=str(r[0]),
                shape_preview=str(r[1] or ""),
                count=int(r[2]),
                victims=int(r[3]),
                archives=int(r[4]),
                sample=str(r[5] or ""),
                sample_archive_sha256=str(r[6] or ""),
                sample_victim_folder=str(r[7] or ""),
                sample_file_path=str(r[8] or ""),
                heuristic_kind=str(r[9] or ""),
                filenames=list(r[10] or []),
            )
            for r in rows
        ]
        return out, total, self._page_count(total, limit)

    async def global_stats(self) -> ParseFailureStats:
        """Corpus-wide tiles. total/parsed are computed live against
        file_audit JOIN extracted_records with dedup by (archive, victim,
        filename), matching the per-victim drawer definition. We bypass
        file_audit_per_victim on purpose: its parsed_files column is
        set from extractor_touched (ulpextract only) and does not count
        gotractor emissions, so the MV materially understates coverage.

        fail_files + shape_buckets come from the same LEFT JOIN the shape
        list uses. crash_files is a cheap count against file_audit where
        parse_error is set."""
        # v1.3.1: anti-join against extracted_file_paths MV instead of
        # scanning extracted_records with FINAL. See list_shapes.
        parsed_in = f"fa.rel_path IN (SELECT file_path FROM {self._db}.extracted_file_paths)"  # noqa: S608  # nosec B608
        cov_rows = await self._rows(
            "SELECT "  # noqa: S608
            "  uniqExact((fa.archive_sha256, fa.victim_folder, fa.filename)) AS total, "
            "  uniqExactIf((fa.archive_sha256, fa.victim_folder, fa.filename), "
            f"             {parsed_in}) AS parsed "
            f"FROM {self._db}.file_audit AS fa "  # nosec B608
            "WHERE fa.victim_folder != '' "
            "  AND fa.heuristic_kind NOT IN ('empty','binary')",
            {},
        )
        total_files = int(cov_rows[0][0] or 0) if cov_rows else 0
        parsed_files = int(cov_rows[0][1] or 0) if cov_rows else 0
        coverage_pct = round(100.0 * parsed_files / total_files, 1) if total_files else 0.0

        fail_rows = await self._rows(
            f"SELECT count(), uniqExact({self._SIG_EXPR}) "  # noqa: S608
            f"FROM {self._db}.file_audit AS fa "  # nosec B608
            "WHERE fa.victim_folder != '' "
            "  AND fa.heuristic_kind NOT IN ('empty','binary') "
            f"  AND NOT ({parsed_in})",
            {},
        )
        fail_files = int(fail_rows[0][0] or 0) if fail_rows else 0
        shape_buckets = int(fail_rows[0][1] or 0) if fail_rows else 0

        crash_rows = await self._rows(
            f"SELECT count() FROM {self._db}.file_audit FINAL "  # noqa: S608  # nosec B608
            "WHERE parse_error != ''",
            {},
        )
        crash_files = int(crash_rows[0][0] or 0) if crash_rows else 0

        return ParseFailureStats(
            total_files=total_files,
            parsed_files=parsed_files,
            coverage_pct=coverage_pct,
            fail_files=fail_files,
            shape_buckets=shape_buckets,
            crash_files=crash_files,
        )

    async def shape_samples(self, shape_sig: str, *, limit: int = 50) -> list[ParseFailureSample]:
        """Raw sample rows for one shape bucket. Used by the workbench
        detail panel + the 'Draft rule from file' pre-fill."""
        rows = await self._rows(
            "SELECT fa.archive_sha256, fa.victim_folder, fa.rel_path, "  # noqa: S608
            "       fa.filename, fa.size_bytes, fa.sample_head, "
            "       fa.heuristic_kind "
            f"FROM {self._db}.file_audit AS fa "  # nosec B608
            "WHERE fa.victim_folder != '' "
            "  AND fa.heuristic_kind NOT IN ('empty','binary') "
            f"  AND fa.rel_path NOT IN (SELECT file_path FROM {self._db}.extracted_file_paths) "
            f"  AND {self._SIG_EXPR} = {{sig:String}} "
            "LIMIT {limit:UInt32}",
            {"sig": shape_sig, "limit": int(limit)},
        )
        return [
            ParseFailureSample(
                archive_sha256=str(r[0]),
                victim_folder=str(r[1]),
                file_path=str(r[2]),
                filename=str(r[3]),
                size_bytes=int(r[4]),
                sample_head=str(r[5] or ""),
                heuristic_kind=str(r[6] or ""),
            )
            for r in rows
        ]


__all__ = [
    "ArtifactCardRow",
    "ArtifactDetailRow",
    "ArtifactDomainRow",
    "ArtifactFileRow",
    "ArtifactRecordRow",
    "AuditSearchRow",
    "Bucket",
    "CoverageRow",
    "CredRow",
    "FileAuditReader",
    "ParseFailureSample",
    "ParseFailureShape",
    "ParseFailureStats",
    "SampleRow",
    "StealerArtifactsReader",
    "StealerCredsReader",
    "StealerFailuresReader",
    "StealerStats",
    "UnknownRow",
]
