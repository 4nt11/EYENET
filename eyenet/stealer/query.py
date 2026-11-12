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


__all__ = ["Bucket", "CredRow", "StealerCredsReader", "StealerStats"]
