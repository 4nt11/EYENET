# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read side of the ULP corpus: stats + credential search over ClickHouse stealer.creds.

Backs the read:stealer API (overview charts + host search). Queries are parameterized
(clickhouse-connect bound params) so the operator's search term can't inject SQL.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from eyenet.stealer.clickhouse import (
    clickhouse_db,
    get_async_clickhouse_client,
    get_clickhouse_client,
)

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
            scalars = (
                self._c()
                .query(
                    "SELECT count(), uniqExact((host,login,password)), uniqExact(host) "
                    "FROM {db:Identifier}.creds",
                    parameters=db,
                )
                .result_rows[0]
            )
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
            rows = (
                self._c()
                .query(
                    # `where` is a code constant (not user input); the search term + db + limits
                    # are all bound params, so the f-string only splices our own literal.
                    "SELECT host,url,login,password,scheme,tld FROM {db:Identifier}.creds "  # noqa: S608  # nosec B608
                    f"{where} ORDER BY host LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}",
                    parameters=params,
                )
                .result_rows
            )
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

    def _rows(self, sql: str, params: dict[str, object]) -> list[tuple[Any, ...]]:
        try:
            return self._c().query(sql, parameters=params).result_rows  # type: ignore[return-value]
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

    def coverage(self, *, page: int, limit: int) -> tuple[list[CoverageRow], int, int]:
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

    def unknown(self, *, page: int, limit: int) -> tuple[list[UnknownRow], int, int]:
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

    def samples(self, *, filename: str, page: int, limit: int) -> tuple[list[SampleRow], int, int]:
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

    def search(self, *, q: str, page: int, limit: int) -> tuple[list[AuditSearchRow], int, int]:
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
            "SELECT archive_sha256, rel_path, filename, heuristic_kind, size_bytes,"  # nosec B608  # noqa: S608
            "       substring(sample_head,"
            "                 greatest(1, positionCaseInsensitive(sample_head, {q:String}) - 80),"
            "                 200) AS match_context"
            f"  FROM {{db:Identifier}}.file_audit"
            f"  WHERE {where}"
            "   ORDER BY parsed_at DESC"
            "   LIMIT {lim:UInt32} OFFSET {off:UInt32}",
            {"db": self._db, "q": q, "lim": int(limit), "off": int(off)},
        )
        total = self._scalar(
            f"SELECT count() FROM {{db:Identifier}}.file_audit WHERE {where}",  # noqa: S608  # nosec B608
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
    ) -> tuple[list[ArtifactCardRow], int, int]:
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

        where_sql = " AND ".join(where)
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        total_rows = await self._rows(
            f"SELECT count() FROM {self._db}.victim_profiles WHERE {where_sql}",  # nosec B608  # noqa: S608
            params,
        )
        total = int(total_rows[0][0]) if total_rows else 0

        rows = await self._rows(
            "SELECT "  # noqa: S608
            "  archive_sha256, victim_folder, country, traffic_affid, build_version, "
            "  creds_count, cookies_count, wallet_vaults_count, "
            "  has_corporate_marker, has_wallet, has_crypter_banner "
            f"FROM {self._db}.victim_profiles "  # nosec B608
            f"WHERE {where_sql} "
            "ORDER BY (archive_sha256, victim_folder) "
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
            f"FROM {self._db}.victim_profiles "  # nosec B608
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
        fired, hits = await asyncio.gather(
            self._rows(
                "SELECT DISTINCT rule_id "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
                "WHERE archive_sha256 = {sha:FixedString(64)} "
                "  AND splitByChar('/', file_path)[2] = {vf:String}",
                {"sha": archive_sha256, "vf": victim_folder},
            ),
            self._monitored_domain_hits(archive_sha256, victim_folder),
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
        )

    async def _monitored_domain_hits(self, archive_sha256: str, victim_folder: str) -> int:
        """Count distinct monitored-watchlist domains this victim touched.

        Joins ``victim_domains`` against ``monitored_domains`` by exact or
        suffix match depending on each row's ``match_type``. Returns 0 if
        the monitored_domains table has no rows (watchlist not seeded yet),
        which is the common early-stage state.
        """
        rows = await self._rows(
            "SELECT uniqExact(vd.domain) AS n "  # noqa: S608
            f"FROM {self._db}.victim_domains AS vd "  # nosec B608
            f"INNER JOIN {self._db}.monitored_domains AS md "
            "  ON (md.match_type = 'exact'  AND vd.domain = md.domain) "
            "  OR (md.match_type = 'suffix' AND endsWith(vd.domain, md.domain)) "
            "WHERE vd.archive_sha256 = {sha:FixedString(64)} "
            "  AND vd.victim_folder  = {vf:String}",
            {"sha": archive_sha256, "vf": victim_folder},
        )
        return int(rows[0][0]) if rows else 0

    async def file_tree(self, archive_sha256: str, victim_folder: str) -> list[ArtifactFileRow]:
        rows = await self._rows(
            "SELECT rel_path, filename, size_bytes, heuristic_kind, "  # noqa: S608
            "       extractor_touched, rows_emitted, sample_head, file_sha256 "
            f"FROM {self._db}.file_audit "  # nosec B608
            "WHERE archive_sha256 = {sha:FixedString(64)} "
            "  AND victim_folder = {vf:String} "
            "ORDER BY rel_path",
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

    async def records(
        self,
        archive_sha256: str,
        victim_folder: str,
        *,
        page: int,
        limit: int,
        rule_id: str | None = None,
        family: str | None = None,
    ) -> tuple[list[ArtifactRecordRow], int, int]:
        where = [
            "archive_sha256 = {sha:FixedString(64)}",
            "splitByChar('/', file_path)[2] = {vf:String}",
        ]
        params: dict[str, object] = {"sha": archive_sha256, "vf": victim_folder}
        if rule_id:
            where.append("rule_id = {rid:String}")
            params["rid"] = rule_id
        if family:
            where.append("family = {fam:String}")
            params["fam"] = family
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset
        where_sql = " AND ".join(where)

        total_rows, rows = await asyncio.gather(
            self._rows(
                f"SELECT count() FROM {self._db}.extracted_records WHERE {where_sql}",  # nosec B608  # noqa: S608
                params,
            ),
            self._rows(
                "SELECT rule_id, family, file_path, fields "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
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
    "SampleRow",
    "StealerArtifactsReader",
    "StealerCredsReader",
    "StealerStats",
    "UnknownRow",
]
