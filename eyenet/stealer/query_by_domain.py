# SPDX-License-Identifier: AGPL-3.0-or-later
"""ClickHouse queries backing /v1/stealer/by-domain/{domain}/*.

One reader class, one method per endpoint. All methods canonicalise the
operator's input to the registrable domain first (via tldextract) so
``www.test.com`` and ``test.com`` land on the same query. The host match
is equality on the registrable domain OR a subdomain match via
``endsWith(lower_host, '.' || canonical)``; this keeps the WHERE clause
cheap and avoids regex.

No FINAL anywhere: extracted_records is a 100M-row ReplacingMergeTree
and FINAL merged all parts in memory per query. The projected columns
plus ``countDistinct`` / ``SELECT DISTINCT`` reproduce the same dedup
grain. See v1.3.4.4 release notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

import tldextract

from eyenet.stealer.clickhouse import clickhouse_db, get_async_clickhouse_client


class StealerCorpusUninitializedError(Exception):
    """Raised when the stealer CH tables do not exist yet (fresh install)."""


def _decode_jwt(token: str) -> tuple[dict[str, object] | None, str | None]:
    """Decode a JWT's header + payload. Returns (claims, alg) or (None, None).

    Does NOT verify the signature. These tokens come from leaked data; we are
    reading them for intelligence, not authenticating a request. A malformed
    token returns (None, None) silently so operator triage keeps flowing.
    """
    import base64  # noqa: PLC0415
    import json  # noqa: PLC0415

    jwt_part_count = 3  # header.payload.signature
    try:
        parts = token.strip().split(".")
        if len(parts) != jwt_part_count:
            return None, None
        header_b64, payload_b64, _sig = parts
        # base64url requires padding for std lib decoder.
        pad = "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + pad)
        claims = json.loads(payload_bytes)
        if not isinstance(claims, dict):
            return None, None
        hdr_pad = "=" * (-len(header_b64) % 4)
        hdr_bytes = base64.urlsafe_b64decode(header_b64 + hdr_pad)
        hdr = json.loads(hdr_bytes)
        alg = hdr.get("alg") if isinstance(hdr, dict) else None
        return claims, str(alg) if alg else None
    except Exception:
        return None, None


def _exp_to_datetime(claims: dict[str, object] | None) -> datetime | None:
    if not claims:
        return None
    exp = claims.get("exp")
    if not isinstance(exp, int | float):
        return None
    try:
        return datetime.fromtimestamp(float(exp), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _is_jwt_expired(exp_at: datetime | None) -> bool:
    """Null-exp is treated as expired for conservative operator triage."""
    if exp_at is None:
        return True
    return exp_at < datetime.now(tz=UTC)


def _aud_as_string(claims: dict[str, object] | None) -> str | None:
    """`aud` can be a string or an array per RFC 7519. Normalise to a comma
    list so the DTO stays simple."""
    if not claims:
        return None
    aud = claims.get("aud")
    if isinstance(aud, str):
        return aud
    if isinstance(aud, list):
        return ", ".join(str(x) for x in aud)
    return None


def canonicalize(raw: str) -> str:
    """Return the registrable domain of ``raw``.

    ``www.test.com`` -> ``test.com``. For input without a known public
    suffix (e.g. ``localhost``, raw IPs, a bare private label), returns
    the input stripped and lowered so the equality branch still matches.
    """
    cleaned = raw.strip().lower().rstrip(".")
    ext = tldextract.extract(cleaned)
    if ext.suffix and ext.domain:
        return f"{ext.domain}.{ext.suffix}"
    return cleaned


def _is_unknown_table(exc: Exception) -> bool:
    msg = str(exc)
    return "UNKNOWN_TABLE" in msg or "doesn't exist" in msg or "Code: 60" in msg


@dataclass(frozen=True, slots=True)
class CredRow:
    host: str
    url: str
    login: str
    password: str
    scheme: str
    archive_sha256: str
    victim_folder: str
    ingested_at: datetime


@dataclass(frozen=True, slots=True)
class VictimRow:
    archive_sha256: str
    victim_folder: str
    country: str
    build_version: str
    credential_count: int
    cookie_count: int
    first_seen_at: datetime | None
    loader_md5: str | None = None


@dataclass(frozen=True, slots=True)
class SubdomainRow:
    host: str
    credential_count: int
    cookie_count: int


@dataclass(frozen=True, slots=True)
class CookieRow:
    host: str
    name: str
    value: str
    expires_at: datetime | None
    http_only: bool
    secure: bool
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class AutofillRow:
    host: str
    field_name: str
    value: str
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class HistoryRow:
    host: str
    url: str
    title: str
    visit_count: int
    last_visit_at: datetime | None
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class LocalStorageJwtRow:
    host: str
    key: str
    jwt_value: str
    jwt_subject: str | None
    jwt_issuer: str | None
    jwt_audience: str | None
    jwt_algorithm: str | None
    expires_at: datetime | None
    is_expired: bool
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class IndicatorRow:
    rule_id: str
    rule_name: str
    severity: str
    hit_count: int
    first_hit_at: datetime | None
    last_hit_at: datetime | None


@dataclass(frozen=True, slots=True)
class DomainSummaryRow:
    canonical_domain: str
    victim_count: int
    archive_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    credential_count: int
    live_cookie_count: int
    all_cookie_count: int
    autofill_count: int
    history_count: int
    localstorage_jwt_count: int
    indicator_hit_count: int


class DomainCorpusReader:
    """Reverse-lookup queries over the stealer corpus keyed on a domain."""

    # Family inventory (see rules/catalog/*.yaml). Grouped by the Domain View
    # tab each one feeds. Kept here (not on StealerCredsReader) so adding a
    # new family to a tab is a one-line change in one place.
    _CRED_FAMILIES: ClassVar[list[str]] = [
        "browser_passwords",
        "windows_credentials",
        "firefox_logins",
        "combolist",
    ]
    _COOKIE_FAMILIES: ClassVar[list[str]] = ["cookies", "victim_cookies"]
    _AUTOFILL_FAMILIES: ClassVar[list[str]] = ["browser_autofills", "victim_autofills"]
    _HISTORY_FAMILIES: ClassVar[list[str]] = ["victim_history", "victim_downloads"]
    _LOCALSTORAGE_JWT_RULE: ClassVar[str] = "localstorage_jwt_candidates"

    # Reused from StealerCredsReader. Lowered coalesce over the fields we
    # canonicalise host into. Any change here must mirror there.
    _HOST_EXPR: ClassVar[str] = (
        "lower(coalesce("
        "nullIf(domain(fields['url']), ''), "
        "nullIf(domain(fields['host']), ''), "
        "nullIf(fields['host'], ''), ''))"
    )
    _SCHEME_EXPR: ClassVar[str] = (
        "lower(coalesce(nullIf(fields['scheme'], ''), nullIf(protocol(fields['url']), ''), ''))"
    )

    def __init__(self) -> None:
        self._db = clickhouse_db()
        self._client: Any | None = None

    async def _c(self) -> Any:
        if self._client is None:
            self._client = await get_async_clickhouse_client()
        return self._client

    def _host_predicate(self) -> str:
        """SQL predicate: equality on the MATERIALIZED host_registrable column.

        v1.3.6: the column is populated at insert time via
        ``cutToFirstSignificantSubdomain(lower(coalesce(domain(url), ...)))``
        and backed by a bloom_filter(0.01) GRANULARITY 4 skip index. One
        equality check prunes to ~0.3% of granules (measured 749/12315 on
        prod for google.com) + 0.16% empirical false-positive rate (measured,
        6x tighter than the configured target). Subdomain match comes for
        free because host_registrable is already the registrable form.
        """
        return "host_registrable = {d:String}"

    def _base_params(self, canonical: str) -> dict[str, object]:
        return {"d": canonical}

    async def summary(self, canonical: str) -> DomainSummaryRow:
        """Hero card numbers. v1.3.6: reads the ``by_domain_counts`` sibling
        (ReplacingMergeTree, 231k registrables, refreshed every 5 min). FINAL
        is cheap on a 231k-row table; measured 45 ms warm, 560 ms cold. Zero
        state-blob deserialization, no heavy aggregation at read time."""
        client = await self._c()
        try:
            res = await client.query(
                "SELECT host_registrable, victim_count, archive_count, "  # noqa: S608
                "       first_seen_at, last_seen_at, credential_count, "
                "       live_cookie_count, all_cookie_count, autofill_count, "
                "       history_count, localstorage_jwt_count, indicator_hit_count "
                f"FROM {self._db}.by_domain_counts FINAL "  # nosec B608
                "WHERE host_registrable = {d:String}",
                parameters=self._base_params(canonical),
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.by_domain_counts does not exist yet"
                ) from exc
            raise
        if not res.result_rows:
            return DomainSummaryRow(canonical, 0, 0, None, None, 0, 0, 0, 0, 0, 0, 0)
        r = res.result_rows[0]
        return DomainSummaryRow(
            canonical_domain=r[0] or canonical,
            victim_count=int(r[1] or 0),
            archive_count=int(r[2] or 0),
            first_seen_at=r[3],
            last_seen_at=r[4],
            credential_count=int(r[5] or 0),
            live_cookie_count=int(r[6] or 0),
            all_cookie_count=int(r[7] or 0),
            autofill_count=int(r[8] or 0),
            history_count=int(r[9] or 0),
            localstorage_jwt_count=int(r[10] or 0),
            indicator_hit_count=int(r[11] or 0),
        )

    async def credentials(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[CredRow], int]:
        """Paginated credentials for this domain + total."""
        client = await self._c()
        hp = self._host_predicate()
        params = {
            **self._base_params(canonical),
            "fams": self._CRED_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total = await client.query(
                "SELECT countDistinct((fields['url'], fields['login'], fields['password'])) "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, fields['url'] u, fields['login'] l, "  # noqa: S608
                f"       fields['password'] p, {self._SCHEME_EXPR} s, "
                "       archive_sha256, victim_folder, ingested_at "
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp} "
                "ORDER BY ingested_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            CredRow(
                host=r[0], url=r[1], login=r[2], password=r[3], scheme=r[4],
                archive_sha256=r[5], victim_folder=r[6], ingested_at=r[7],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def victims(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[VictimRow], int]:
        """Victims affected, ordered by first_seen_at DESC.

        v1.3.8: reads the by_domain_victim_counts sibling (ReplacingMergeTree,
        keyed on (host_registrable, archive, victim), ~730k rows on prod).
        Measured: single-stage original 574ms warm; two-stage interim 149ms;
        this one-stage sibling lookup 12-16ms warm, 679ms cold. Counts are up
        to 5 minutes stale because the sibling refreshes on that cadence.

        Per-victim cred_count / cookie_count are DOMAIN-SCOPED unique triples
        (one victim's unique google.com creds). The hero's credential_count
        on by_domain_counts is DOMAIN-WIDE unique triples (across victims),
        so sum(victims.cred_count) >= hero.credential_count when operators
        see the same cred leaked by multiple victims. This is a correct
        semantic distinction, not a bug.
        """
        client = await self._c()
        params = {
            **self._base_params(canonical),
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total = await client.query(
                "SELECT count() "  # noqa: S608
                f"FROM {self._db}.by_domain_victim_counts FINAL "
                "WHERE host_registrable = {d:String}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                "SELECT archive_sha256, victim_folder, country, build_version, "  # noqa: S608
                "       cred_count, cookie_count, first_seen_at, "
                "       nullIf(loader_md5, '') AS md5 "
                f"FROM {self._db}.by_domain_victim_counts FINAL "
                "WHERE host_registrable = {d:String} "
                "ORDER BY first_seen_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.by_domain_victim_counts"
                ) from exc
            raise
        items = [
            VictimRow(
                archive_sha256=r[0], victim_folder=r[1],
                country=r[2] or "", build_version=r[3] or "",
                credential_count=int(r[4] or 0), cookie_count=int(r[5] or 0),
                first_seen_at=r[6],
                loader_md5=r[7],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def subdomains(self, *, canonical: str, limit: int) -> tuple[list[SubdomainRow], int]:
        """Top-N subdomains by credential volume."""
        client = await self._c()
        hp = self._host_predicate()
        params = {
            **self._base_params(canonical),
            "creds": self._CRED_FAMILIES,
            "cookies": self._COOKIE_FAMILIES,
            "lim": int(limit),
        }
        try:
            total = await client.query(
                f"SELECT countDistinct({self._HOST_EXPR}) "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                f"WHERE {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT {self._HOST_EXPR} AS host, "  # noqa: S608
                "       countDistinctIf((fields['url'], fields['login'], fields['password']), "
                "         family IN {creds:Array(String)}) AS cred_cnt, "
                "       countDistinctIf((fields['url'], fields['name']), "
                "         family IN {cookies:Array(String)}) AS cookie_cnt "
                f"FROM {self._db}.extracted_records "
                f"WHERE {hp} "
                "GROUP BY host "
                "ORDER BY cred_cnt DESC "
                "LIMIT {lim:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            SubdomainRow(host=r[0], credential_count=int(r[1] or 0), cookie_count=int(r[2] or 0))
            for r in rows.result_rows
        ]
        return items, total_n

    async def cookies(
        self, *, canonical: str, limit: int, offset: int, live_only: bool
    ) -> tuple[list[CookieRow], int]:
        client = await self._c()
        hp = self._host_predicate()
        live_filter = (
            " AND parseDateTimeBestEffortOrNull(fields['expires']) > now()" if live_only else ""
        )
        params = {
            **self._base_params(canonical),
            "fams": self._COOKIE_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total = await client.query(
                "SELECT countDistinct((fields['url'], fields['name'])) "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp}{live_filter}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, fields['name'], fields['value'], "  # noqa: S608
                "       parseDateTimeBestEffortOrNull(fields['expires']) AS expires_at, "
                "       toUInt8(coalesce(fields['http_only'], '0') "
                "         IN ('1', 'true', 'TRUE', 'True')) AS http_only, "
                "       toUInt8(coalesce(fields['secure'], '0') "
                "         IN ('1', 'true', 'TRUE', 'True')) AS secure, "
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp}{live_filter} "
                "ORDER BY ingested_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            CookieRow(
                host=r[0], name=r[1], value=r[2], expires_at=r[3],
                http_only=bool(r[4]), secure=bool(r[5]),
                archive_sha256=r[6], victim_folder=r[7],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def autofills(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[AutofillRow], int]:
        client = await self._c()
        hp = self._host_predicate()
        params = {
            **self._base_params(canonical),
            "fams": self._AUTOFILL_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total = await client.query(
                "SELECT countDistinct((fields['name'], fields['value'])) "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, fields['name'], fields['value'], "  # noqa: S608
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp} "
                "ORDER BY ingested_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            AutofillRow(
                host=r[0], field_name=r[1], value=r[2],
                archive_sha256=r[3], victim_folder=r[4],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def history(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[HistoryRow], int]:
        client = await self._c()
        hp = self._host_predicate()
        params = {
            **self._base_params(canonical),
            "fams": self._HISTORY_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total = await client.query(
                "SELECT countDistinct(fields['url']) "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, fields['url'], fields['title'], "  # noqa: S608
                "       toUInt64OrZero(coalesce(fields['visit_count'], '0')) AS vc, "
                "       parseDateTimeBestEffortOrNull(fields['last_visit']) AS lv, "
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "
                f"WHERE family IN {{fams:Array(String)}} AND {hp} "
                "ORDER BY lv DESC NULLS LAST, ingested_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            HistoryRow(
                host=r[0], url=r[1], title=r[2] or "",
                visit_count=int(r[3] or 0), last_visit_at=r[4],
                archive_sha256=r[5], victim_folder=r[6],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def localstorage_jwts(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[LocalStorageJwtRow], int, int]:
        """Leaked JWTs held in victims' browser localStorage for this domain.

        Returns (items, total, live_count). Server-side decodes each JWT's
        payload (base64url + JSON) to surface sub/iss/aud/exp claims. Does
        NOT verify the signature; these are stolen tokens, verification is
        meaningless. ``is_expired`` is computed against now(); a null-exp
        claim is treated as expired to keep operator triage conservative.

        v1.3.9: the localstorage_jwt_candidates rule was renamed in the
        same release to emit {host, name, value} in place of the
        pre-v2 ls_jwt_* fields, so host_registrable now auto-populates
        via the materialized column and the WHERE uses the bloom index.
        """
        client = await self._c()
        params = {
            **self._base_params(canonical),
            "lim": int(limit),
            "off": int(offset),
        }
        try:
            total_res = await client.query(
                "SELECT count() "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                "WHERE rule_id = 'localstorage_jwt_candidates' "
                "  AND host_registrable = {d:String}",
                parameters=params,
            )
            total_n = int(total_res.result_rows[0][0]) if total_res.result_rows else 0
            page_res = await client.query(
                "SELECT fields['host'], fields['name'], fields['value'], "  # noqa: S608
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "
                "WHERE rule_id = 'localstorage_jwt_candidates' "
                "  AND host_registrable = {d:String} "
                "ORDER BY ingested_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
            # Live count: decode every matching JWT to count non-expired ones.
            # Bounded by total_n (hundreds at scale we have today); add an
            # exp MATERIALIZED column later if this ever becomes hot.
            live_res = await client.query(
                "SELECT fields['value'] "  # noqa: S608
                f"FROM {self._db}.extracted_records "
                "WHERE rule_id = 'localstorage_jwt_candidates' "
                "  AND host_registrable = {d:String}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items: list[LocalStorageJwtRow] = []
        for row in page_res.result_rows:
            claims, alg = _decode_jwt(str(row[2]))
            exp_at = _exp_to_datetime(claims)
            items.append(
                LocalStorageJwtRow(
                    host=str(row[0] or ""),
                    key=str(row[1] or ""),
                    jwt_value=str(row[2] or ""),
                    jwt_subject=claims.get("sub") if claims else None,
                    jwt_issuer=claims.get("iss") if claims else None,
                    jwt_audience=_aud_as_string(claims),
                    jwt_algorithm=alg,
                    expires_at=exp_at,
                    is_expired=_is_jwt_expired(exp_at),
                    archive_sha256=str(row[3]),
                    victim_folder=str(row[4]),
                )
            )
        live_count = 0
        now = datetime.now(tz=UTC).timestamp()
        for row in live_res.result_rows:
            claims, _ = _decode_jwt(str(row[0]))
            exp = claims.get("exp") if claims else None
            if isinstance(exp, int | float) and exp > now:
                live_count += 1
        return items, total_n, live_count

    async def indicators(self, canonical: str) -> list[IndicatorRow]:
        """Rule catalog hits. No pagination, usually O(10s) of rules."""
        client = await self._c()
        hp = self._host_predicate()
        params = self._base_params(canonical)
        try:
            # rule_name + severity come from the catalog YAML, not CH. Return
            # rule_id + aggregate counts here; the handler can enrich from the
            # rule catalog in-process.
            rows = await client.query(
                "SELECT rule_id, "  # noqa: S608
                "       countDistinct((archive_sha256, victim_folder, file_path, "
                "                      cityHash64(toString(fields)))) AS hits, "
                "       min(ingested_at) AS first_hit, max(ingested_at) AS last_hit "
                f"FROM {self._db}.extracted_records "
                f"WHERE rule_id != '' AND {hp} "
                "GROUP BY rule_id "
                "ORDER BY hits DESC",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        # rule_name + severity resolution deferred to the handler.
        return [
            IndicatorRow(
                rule_id=r[0], rule_name="", severity="info",
                hit_count=int(r[1] or 0), first_hit_at=r[2], last_hit_at=r[3],
            )
            for r in rows.result_rows
        ]
