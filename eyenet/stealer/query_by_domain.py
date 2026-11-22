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


def _claim_str(claims: dict[str, object] | None, key: str) -> str | None:
    if not claims:
        return None
    v = claims.get(key)
    return v if isinstance(v, str) else None


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
    user: str
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
    # v1.3.10 semantics shift: stealer-emitted autofills carry no URL (the
    # Chromium `Web Data` autofill table is keyed on name+value, not domain).
    # So "autofills for google.com" is meaningless; we now return autofills
    # from the VICTIM POOL that leaked to google.com -- i.e. what those
    # victims typed into forms anywhere. The `host` field is dropped because
    # the rendered row no longer has a per-domain meaning.
    field_name: str
    value: str
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class HistoryRow:
    # v1.3.10: gotractor's history rule emits visit_url + visit_title only.
    # No visit_count, no last_visit timestamp -- Chromium's `History` DB
    # carries both, but the parsing rule skips them. Keeping the fields here
    # as 0 / None so the DTO shape stays stable; wire real values when the
    # rule is extended.
    host: str
    url: str
    title: str
    visit_count: int
    last_visit_at: datetime | None
    archive_sha256: str
    victim_folder: str


@dataclass(frozen=True, slots=True)
class SampleRow:
    # v1.3.10 Samples tab: one row per distinct loader/payload MD5
    # across the victim pool for this domain. family_slug comes from
    # victim_family_verdict (classifier output, slug like 'stealc',
    # 'lumma', 'redline'). top_bypass_* precomputed on the backend so
    # the list view can colour-code the row without calling the detail
    # endpoint; av_name='' + rate=0 means no AV overlap for this md5.
    loader_md5: str
    family_slug: str
    victim_count: int
    archive_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    top_bypass_av_name: str
    top_bypass_rate: float


@dataclass(frozen=True, slots=True)
class SampleLoaderPath:
    path: str
    victim_count: int


@dataclass(frozen=True, slots=True)
class SampleAvBreakdown:
    av_name: str
    active_count: int
    total_count: int


@dataclass(frozen=True, slots=True)
class SampleDetail:
    # Drill-down payload fetched when the operator expands a sample row.
    # Keeps the list query cheap; this one only runs on explicit click.
    loader_paths: list[SampleLoaderPath]
    av_breakdown: list[SampleAvBreakdown]


@dataclass(frozen=True, slots=True)
class AntivirusRow:
    # v1.3.10 Antiviruses tab: per-AV aggregate across the victim pool
    # that leaked to this domain. State breakdown lets the UI render the
    # stacked active/disabled/unknown bar. Bypass rate is computed FE-side
    # as active_count/victim_count. av_name == '' is the null-AV bucket
    # (victims in the pool whose fingerprint lacks os_av_name).
    av_name: str
    victim_count: int
    active_count: int
    disabled_count: int
    unknown_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None


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
        """Hero card numbers.

        v1.3.12.2: by_domain_counts is now an incremental AggregatingMergeTree
        (every INSERT into extracted_records adds per-host HLL12 state
        deltas, CH merges in the background). Reads decode with
        uniqHLL12Merge(state_col) + GROUP BY host_registrable. Three
        columns that are not persisted in state:

          autofill_count       -- per-host aggregate is always 0 because
                                  autofill rows carry no host_registrable;
                                  we pool-sum across victim_counts.autofills
                                  via the by_domain_victim_counts join.
          live_cookie_count    -- time-dependent (now() drifts), computed
                                  here against extracted_records with the
                                  host_registrable bloom-indexed predicate.
          indicator_hit_count  -- the real indicator concept is a join
                                  against monitored_domains; still 0 here
                                  until that's wired.
        """
        import asyncio  # noqa: PLC0415

        client = await self._c()
        params = self._base_params(canonical)
        try:
            summary_coro = client.query(
                "SELECT host_registrable, "  # noqa: S608
                "       uniqHLL12Merge(victim_count_state)     AS victim_count, "
                "       uniqHLL12Merge(archive_count_state)    AS archive_count, "
                "       min(first_seen_at)                     AS first_seen_at, "
                "       max(last_seen_at)                      AS last_seen_at, "
                "       uniqHLL12Merge(credential_count_state) AS credential_count, "
                "       uniqHLL12Merge(all_cookie_count_state) AS all_cookie_count, "
                "       uniqHLL12Merge(history_count_state)    AS history_count, "
                "       uniqHLL12Merge(localstorage_jwt_count_state) AS localstorage_jwt_count "
                f"FROM {self._db}.by_domain_counts "  # nosec B608
                "WHERE host_registrable = {d:String} "
                "GROUP BY host_registrable",
                parameters=params,
            )
            autofill_coro = client.query(
                # Pool-join sum: tallies each victim's own autofill count
                # once. See the autofills() tab method for the corresponding
                # paginated view. Both numbers describe the same slice.
                "SELECT toUInt64(coalesce(sum(vc.autofills_count), 0)) "  # noqa: S608
                f"FROM {self._db}.by_domain_victim_counts AS bvc FINAL "  # nosec B608
                f"INNER JOIN {self._db}.victim_counts AS vc FINAL "
                "  USING (archive_sha256, victim_folder) "
                "WHERE bvc.host_registrable = {d:String}",
                parameters=params,
            )
            # live_cookie_count computed at read time: the AggregatingMergeTree
            # cannot carry a now()-dependent filter without re-aggregating on
            # every tick. The host_registrable bloom index keeps the scan
            # tight (same row volume as one page of the Cookies tab).
            live_cookie_coro = client.query(
                "SELECT uniqHLL12((trim(LEADING '.' FROM fields['cookie_domain']), "  # noqa: S608
                "       coalesce(nullIf(fields['cookie_name'], ''), fields['name']))) "
                f"FROM {self._db}.extracted_records "  # nosec B608
                "WHERE host_registrable = {d:String} "
                "  AND family IN ('cookies','victim_cookies') "
                "  AND fromUnixTimestamp(toUInt32OrZero(coalesce("
                "        nullIf(fields['cookie_expires_epoch'], ''), "
                "        nullIf(fields['expires_epoch'], ''), '0'))) > now()",
                parameters=params,
            )
            res, afc_res, live_res = await asyncio.gather(
                summary_coro, autofill_coro, live_cookie_coro
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError(
                    "stealer.by_domain_counts does not exist yet"
                ) from exc
            raise
        autofill_count = int(afc_res.result_rows[0][0]) if afc_res.result_rows else 0
        live_cookie_count = int(live_res.result_rows[0][0]) if live_res.result_rows else 0
        if not res.result_rows:
            return DomainSummaryRow(
                canonical, 0, 0, None, None, 0, live_cookie_count, 0, autofill_count, 0, 0, 0,
            )
        r = res.result_rows[0]
        return DomainSummaryRow(
            canonical_domain=r[0] or canonical,
            victim_count=int(r[1] or 0),
            archive_count=int(r[2] or 0),
            first_seen_at=r[3],
            last_seen_at=r[4],
            credential_count=int(r[5] or 0),
            live_cookie_count=live_cookie_count,
            all_cookie_count=int(r[6] or 0),
            autofill_count=autofill_count,
            history_count=int(r[7] or 0),
            localstorage_jwt_count=int(r[8] or 0),
            indicator_hit_count=0,
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
                "SELECT uniqHLL12((fields['url'], fields['user'], fields['password'])) "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
                f"WHERE family IN {{fams:Array(String)}} AND {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, fields['url'] u, fields['user'] l, "  # noqa: S608
                f"       fields['password'] p, {self._SCHEME_EXPR} s, "
                "       archive_sha256, victim_folder, ingested_at "
                f"FROM {self._db}.extracted_records "  # nosec B608
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
                host=r[0],
                url=r[1],
                user=r[2],
                password=r[3],
                scheme=r[4],
                archive_sha256=r[5],
                victim_folder=r[6],
                ingested_at=r[7],
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
                f"FROM {self._db}.by_domain_victim_counts FINAL "  # nosec B608
                "WHERE host_registrable = {d:String}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                "SELECT archive_sha256, victim_folder, country, build_version, "  # noqa: S608
                "       cred_count, cookie_count, first_seen_at, "
                "       nullIf(loader_md5, '') AS md5 "
                f"FROM {self._db}.by_domain_victim_counts FINAL "  # nosec B608
                "WHERE host_registrable = {d:String} "
                "ORDER BY first_seen_at DESC "
                "LIMIT {lim:UInt32} OFFSET {off:UInt32}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.by_domain_victim_counts") from exc
            raise
        items = [
            VictimRow(
                archive_sha256=r[0],
                victim_folder=r[1],
                country=r[2] or "",
                build_version=r[3] or "",
                credential_count=int(r[4] or 0),
                cookie_count=int(r[5] or 0),
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
                f"SELECT uniqHLL12({self._HOST_EXPR}) "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
                f"WHERE {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT {self._HOST_EXPR} AS host, "  # noqa: S608
                "       uniqHLL12If((fields['url'], fields['user'], fields['password']), "
                "         family IN {creds:Array(String)}) AS cred_cnt, "
                "       uniqHLL12If((fields['url'], fields['name']), "
                "         family IN {cookies:Array(String)}) AS cookie_cnt "
                f"FROM {self._db}.extracted_records "  # nosec B608
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
        params = {
            **self._base_params(canonical),
            "fams": self._COOKIE_FAMILIES,
            "lim": int(limit),
            "off": int(offset),
        }
        # Field-name reality (v1.3.10): gotractor emits cookie_name / cookie_value /
        # cookie_expires_epoch / cookie_secure for victim_cookies, and drops the
        # cookie_ prefix on expires_epoch + secure for the plain cookies family.
        # http_only is NOT extracted by any current rule -> always 0 for now.
        name_expr = "coalesce(nullIf(fields['cookie_name'], ''), fields['name'])"
        value_expr = "coalesce(nullIf(fields['cookie_value'], ''), fields['value'])"
        expires_expr = (
            "fromUnixTimestamp(toUInt32OrZero(coalesce("
            "nullIf(fields['cookie_expires_epoch'], ''), "
            "nullIf(fields['expires_epoch'], ''), '0')))"
        )
        secure_expr = (
            "toUInt8(coalesce(nullIf(fields['cookie_secure'], ''), "
            "fields['secure'], '0') IN ('1', 'true', 'TRUE', 'True'))"
        )
        host_expr = "trim(LEADING '.' FROM fields['cookie_domain'])"
        live_filter = f" AND {expires_expr} > now()" if live_only else ""
        try:
            total = await client.query(
                f"SELECT uniqHLL12(({host_expr}, {name_expr})) "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
                f"WHERE family IN {{fams:Array(String)}} AND {hp}{live_filter}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {host_expr} h, {name_expr} AS n, {value_expr} AS v, "  # noqa: S608
                f"       {expires_expr} AS expires_at, "
                "       0 AS http_only, "
                f"       {secure_expr} AS secure, "
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "  # nosec B608
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
                host=r[0],
                name=r[1],
                value=r[2],
                expires_at=r[3],
                http_only=bool(r[4]),
                secure=bool(r[5]),
                archive_sha256=r[6],
                victim_folder=r[7],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def autofills(
        self, *, canonical: str, limit: int, offset: int
    ) -> tuple[list[AutofillRow], int]:
        # v1.3.10: victim-pool join. Chromium autofills carry no URL, so a
        # per-domain filter would hit zero rows. Instead we build the set of
        # (archive_sha256, victim_folder) pairs that leaked anything to this
        # domain, then return every autofill those victims produced.
        # Real field names in the corpus: form_key / form_value.
        client = await self._c()
        hp = self._host_predicate()
        params = {
            **self._base_params(canonical),
            "fams": ["victim_autofills", "browser_autofills"],
            "lim": int(limit),
            "off": int(offset),
        }
        victim_pool_cte = (
            "WITH victim_pool AS ("  # noqa: S608 # nosec B608
            "  SELECT DISTINCT archive_sha256, victim_folder "
            f"  FROM {self._db}.extracted_records "
            f"  WHERE {hp}"
            ")"
        )
        try:
            # v1.3.10: total via victim_counts.autofills_count pool-sum
            # (~90 ms warm) instead of uniqHLL12((form_key, form_value))
            # across the full autofill family (~430 ms). Same number as the
            # hero stat; see summary() for the shared pattern. Pagination
            # below still works on distinct (form_key, form_value) rows.
            total = await client.query(
                "SELECT toUInt64(coalesce(sum(vc.autofills_count), 0)) "  # noqa: S608
                f"FROM {self._db}.by_domain_victim_counts AS bvc FINAL "  # nosec B608
                f"INNER JOIN {self._db}.victim_counts AS vc FINAL "
                "  USING (archive_sha256, victim_folder) "
                "WHERE bvc.host_registrable = {d:String}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"{victim_pool_cte} "  # noqa: S608
                f"SELECT DISTINCT er.fields['form_key'] AS fk, "
                f"       er.fields['form_value'] AS fv, "
                f"       er.archive_sha256, er.victim_folder "
                f"FROM {self._db}.extracted_records er "  # nosec B608
                f"INNER JOIN victim_pool vp USING (archive_sha256, victim_folder) "
                f"WHERE er.family IN {{fams:Array(String)}} "
                f"ORDER BY er.ingested_at DESC "
                f"LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            AutofillRow(
                field_name=r[0],
                value=r[1],
                archive_sha256=r[2],
                victim_folder=r[3],
            )
            for r in rows.result_rows
        ]
        return items, total_n

    async def antiviruses(
        self,
        *,
        canonical: str,
    ) -> tuple[list[AntivirusRow], int]:
        """Per-AV aggregate for victims that leaked to this domain.

        Returns (rows, domain_total_victims):
          - rows: one AntivirusRow per distinct non-empty os_av_name across
            the victim pool, ranked by victim_count DESC. Each row's state
            counts cover active / disabled / unknown breakdowns.
          - domain_total_victims: distinct (archive, victim) in the pool.
            FE derives the "no AV detected" row as domain_total minus
            sum(named-AV victim_count), and the % denominators from this
            same number (Domain total mode) or sum(named-AV counts)
            (Known-AV subset mode).

        No pagination: AV name cardinality is tiny (dozens) and UI shows
        the whole list ranked.
        """
        client = await self._c()
        params = {
            **self._base_params(canonical),
            "fp_fam": "victim_fingerprint",
        }
        try:
            res = await client.query(
                # Two-stage aggregate. Inner groups per (archive, victim) so
                # ReplacingMergeTree duplicates and multi-row fingerprints
                # collapse to one per victim; outer groups by AV name. Only
                # named AVs land here; the null-AV row is reconstructed FE
                # side from the domain total. av_state is lowered once for
                # consistent countIf matching.
                #
                # Victim pool reads from by_domain_victim_counts
                # (ReplacingMergeTree ORDER BY (host_registrable, archive,
                # victim), the same sibling the Victims tab uses). WHERE on
                # host_registrable is a primary-key range scan: measured ~90ms
                # on prod for google.com. Also keeps the Antiviruses tab's
                # pool semantics identical to the Victims tab (same table),
                # so operator counts never diverge between the two surfaces.
                "WITH victim_pool AS ("  # noqa: S608 # nosec B608
                "  SELECT archive_sha256, victim_folder "
                f"  FROM {self._db}.by_domain_victim_counts FINAL "
                "  WHERE host_registrable = {d:String}"
                "), "
                "victim_av AS ("
                "  SELECT archive_sha256, victim_folder, "
                "         any(fields['os_av_name']) AS av_name, "
                "         any(lower(fields['os_av_state'])) AS av_state, "
                "         min(ingested_at) AS first_seen, "
                "         max(ingested_at) AS last_seen "
                f"  FROM {self._db}.extracted_records er "
                "  INNER JOIN victim_pool vp USING (archive_sha256, victim_folder) "
                "  WHERE er.family = {fp_fam:String} "
                "    AND er.fields['os_av_name'] != '' "
                "  GROUP BY archive_sha256, victim_folder"
                ") "
                "SELECT av_name, "
                "       count() AS victim_count, "
                "       countIf(av_state = 'active') AS active_count, "
                "       countIf(av_state = 'disabled') AS disabled_count, "
                "       countIf(av_state NOT IN ('active','disabled')) AS unknown_count, "
                "       min(first_seen) AS first_seen_at, "
                "       max(last_seen) AS last_seen_at "
                "FROM victim_av "
                "WHERE av_name != '' "
                "GROUP BY av_name "
                "ORDER BY victim_count DESC",
                parameters=params,
            )
            total_res = await client.query(
                # Victim pool size via the same sibling table. Mirrors the
                # Victims tab counter query so the two surfaces always
                # agree on the "N victims for this domain" number.
                "SELECT count() "  # noqa: S608
                f"FROM {self._db}.by_domain_victim_counts FINAL "  # nosec B608
                "WHERE host_registrable = {d:String}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        rows = [
            AntivirusRow(
                av_name=str(r[0] or ""),
                victim_count=int(r[1] or 0),
                active_count=int(r[2] or 0),
                disabled_count=int(r[3] or 0),
                unknown_count=int(r[4] or 0),
                first_seen_at=r[5],
                last_seen_at=r[6],
            )
            for r in res.result_rows
        ]
        domain_total = int(total_res.result_rows[0][0]) if total_res.result_rows else 0
        return rows, domain_total

    async def samples(
        self,
        *,
        canonical: str,
        limit: int = 50,
    ) -> tuple[list[SampleRow], int]:
        """Per-sample aggregate for the Samples tab.

        Returns (rows, domain_total_victims). rows are ranked by victim
        count DESC, capped at ``limit`` (50 covers the long tail). The
        null-sample row ("no loader metadata") is reconstructed FE-side
        from domain_total minus sum(victim_count).

        Measured on prod (v1.3.10, google.com, warm): 293 ms, 249 MiB
        read, 1.18M rows. Dominated by the fingerprint ``fields`` Map
        read. See development/VICTIM_FINGERPRINT_SIBLING_SCOPE.md for
        the sibling-table fix when this becomes hot.
        """
        client = await self._c()
        params = {
            **self._base_params(canonical),
            "fp_fam": "victim_fingerprint",
            "lim": int(limit),
        }
        try:
            res = await client.query(
                "WITH victim_pool AS ("  # noqa: S608 # nosec B608
                "  SELECT archive_sha256, victim_folder "
                f"  FROM {self._db}.by_domain_victim_counts FINAL "
                "  WHERE host_registrable = {d:String}"
                "), "
                "victim_sample AS ("
                "  SELECT er.archive_sha256, er.victim_folder, "
                "         any(er.fields['ui_payload_md5']) AS payload_md5, "
                "         any(er.fields['os_av_name']) AS av_name, "
                "         any(lower(er.fields['os_av_state'])) AS av_state, "
                "         min(er.ingested_at) AS first_seen, "
                "         max(er.ingested_at) AS last_seen "
                f"  FROM {self._db}.extracted_records er "
                "  INNER JOIN victim_pool vp USING (archive_sha256, victim_folder) "
                "  WHERE er.family = {fp_fam:String} "
                "    AND er.fields['ui_payload_md5'] NOT IN ('', 'unknown', '-') "
                "  GROUP BY er.archive_sha256, er.victim_folder"
                "), "
                "victim_full AS ("
                "  SELECT vs.*, coalesce(vd.slug, '') AS family_slug "
                "  FROM victim_sample vs "
                "  LEFT JOIN (SELECT archive_sha256, victim_folder, slug "
                f"             FROM {self._db}.victim_family_verdict FINAL) vd "
                "    USING (archive_sha256, victim_folder)"
                "), "
                "md5_av AS ("
                "  SELECT payload_md5, av_name, "
                "         countIf(av_state = 'active') AS active_c, count() AS total_c "
                "  FROM victim_full WHERE av_name != '' "
                "  GROUP BY payload_md5, av_name"
                "), "
                "md5_top_bypass AS ("
                "  SELECT payload_md5, "
                "         argMax(av_name, active_c / total_c) AS top_bypass_av, "
                "         max(active_c / total_c) AS top_bypass_rate "
                "  FROM md5_av WHERE total_c > 0 "
                "  GROUP BY payload_md5"
                ") "
                "SELECT vf.payload_md5, "
                "       topK(1)(vf.family_slug)[1] AS family, "
                "       count() AS victim_count, "
                "       uniqHLL12(vf.archive_sha256) AS archive_count, "
                "       min(vf.first_seen) AS first_seen, "
                "       max(vf.last_seen) AS last_seen, "
                "       coalesce(any(mtb.top_bypass_av), '') AS top_bypass_av, "
                "       coalesce(max(mtb.top_bypass_rate), toFloat64(0)) AS top_bypass_rate "
                "FROM victim_full vf "
                "LEFT JOIN md5_top_bypass mtb USING (payload_md5) "
                "GROUP BY vf.payload_md5 "
                "ORDER BY victim_count DESC "
                "LIMIT {lim:UInt32}",
                parameters=params,
            )
            total_res = await client.query(
                "SELECT count() "  # noqa: S608
                f"FROM {self._db}.by_domain_victim_counts FINAL "  # nosec B608
                "WHERE host_registrable = {d:String}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        rows = [
            SampleRow(
                loader_md5=str(r[0] or ""),
                family_slug=str(r[1] or ""),
                victim_count=int(r[2] or 0),
                archive_count=int(r[3] or 0),
                first_seen_at=r[4],
                last_seen_at=r[5],
                top_bypass_av_name=str(r[6] or ""),
                top_bypass_rate=float(r[7] or 0.0),
            )
            for r in res.result_rows
        ]
        domain_total = int(total_res.result_rows[0][0]) if total_res.result_rows else 0
        return rows, domain_total

    async def sample_detail(
        self,
        *,
        canonical: str,
        loader_md5: str,
    ) -> SampleDetail:
        """Drill-down payload for one sample. Two queries run in parallel
        would be ideal; sequential here to keep the client code simple -
        the operator only fetches this on explicit expand so the cost is
        a per-click amortisation, not every page load.
        """
        client = await self._c()
        params = {
            **self._base_params(canonical),
            "md5": loader_md5,
            "fp_fam": "victim_fingerprint",
        }
        try:
            paths_res = await client.query(
                "WITH victim_pool AS ("  # noqa: S608
                "  SELECT archive_sha256, victim_folder "
                f"  FROM {self._db}.by_domain_victim_counts FINAL "
                "  WHERE host_registrable = {d:String}"
                ") "
                "SELECT er.fields['ui_payload_path'] AS p, "
                "       uniqHLL12((er.archive_sha256, er.victim_folder)) AS n "
                f"FROM {self._db}.extracted_records er "  # nosec B608
                "INNER JOIN victim_pool vp USING (archive_sha256, victim_folder) "
                "WHERE er.family = {fp_fam:String} "
                "  AND er.fields['ui_payload_md5'] = {md5:String} "
                "  AND er.fields['ui_payload_path'] != '' "
                "GROUP BY p "
                "ORDER BY n DESC "
                "LIMIT 3",
                parameters=params,
            )
            av_res = await client.query(
                "WITH victim_pool AS ("  # noqa: S608 # nosec B608
                "  SELECT archive_sha256, victim_folder "
                f"  FROM {self._db}.by_domain_victim_counts FINAL "
                "  WHERE host_registrable = {d:String}"
                "), vs AS ("
                "  SELECT er.archive_sha256, er.victim_folder, "
                "         any(er.fields['os_av_name']) AS av_name, "
                "         any(lower(er.fields['os_av_state'])) AS av_state "
                f"  FROM {self._db}.extracted_records er "
                "  INNER JOIN victim_pool vp USING (archive_sha256, victim_folder) "
                "  WHERE er.family = {fp_fam:String} "
                "    AND er.fields['ui_payload_md5'] = {md5:String} "
                "  GROUP BY er.archive_sha256, er.victim_folder"
                ") "
                "SELECT av_name, "
                "       countIf(av_state = 'active') AS active_c, "
                "       count() AS total_c "
                "FROM vs "
                "WHERE av_name != '' "
                "GROUP BY av_name "
                "ORDER BY active_c / total_c DESC",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        return SampleDetail(
            loader_paths=[
                SampleLoaderPath(path=str(r[0]), victim_count=int(r[1] or 0))
                for r in paths_res.result_rows
            ],
            av_breakdown=[
                SampleAvBreakdown(
                    av_name=str(r[0]),
                    active_count=int(r[1] or 0),
                    total_count=int(r[2] or 0),
                )
                for r in av_res.result_rows
            ],
        )

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
        # v1.3.10: real history field names are visit_url + visit_title +
        # visit_time (raw string; parsed here instead of in gotractor so the
        # rule survives the format variance DD.MM.YYYY HH:MM:SS /
        # DD.MM.YYYY, HH:MM:SS / ISO8601). Rule does not extract visit_count
        # (the stealer dump drops it). visit_time falls back to ingested_at
        # on rows from older reindexes that landed before the rule was fixed.
        url_expr = "coalesce(nullIf(fields['visit_url'], ''), fields['url'])"
        title_expr = "coalesce(nullIf(fields['visit_title'], ''), fields['title'])"
        lv_expr = "coalesce(parseDateTimeBestEffortOrNull(fields['visit_time']), ingested_at)"
        try:
            total = await client.query(
                f"SELECT uniqHLL12({url_expr}) "  # noqa: S608
                f"FROM {self._db}.extracted_records "  # nosec B608
                f"WHERE family IN {{fams:Array(String)}} AND {hp}",
                parameters=params,
            )
            total_n = int(total.result_rows[0][0]) if total.result_rows else 0
            rows = await client.query(
                f"SELECT DISTINCT {self._HOST_EXPR} h, {url_expr} AS u, "  # noqa: S608
                f"       {title_expr} AS t, "
                f"       toUInt64OrZero(coalesce(fields['visit_count'], '0')) AS vc, "
                f"       {lv_expr} AS lv, "
                f"       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "  # nosec B608
                f"WHERE family IN {{fams:Array(String)}} AND {hp} "
                f"ORDER BY lv DESC, ingested_at DESC "
                f"LIMIT {{lim:UInt32}} OFFSET {{off:UInt32}}",
                parameters=params,
            )
        except Exception as exc:
            if _is_unknown_table(exc):
                raise StealerCorpusUninitializedError("stealer.extracted_records") from exc
            raise
        items = [
            HistoryRow(
                host=r[0],
                url=r[1],
                title=r[2] or "",
                visit_count=int(r[3] or 0),
                last_visit_at=r[4],
                archive_sha256=r[5],
                victim_folder=r[6],
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
                f"FROM {self._db}.extracted_records "  # nosec B608
                "WHERE rule_id = 'localstorage_jwt_candidates' "
                "  AND host_registrable = {d:String}",
                parameters=params,
            )
            total_n = int(total_res.result_rows[0][0]) if total_res.result_rows else 0
            page_res = await client.query(
                "SELECT fields['host'], fields['name'], fields['value'], "  # noqa: S608
                "       archive_sha256, victim_folder "
                f"FROM {self._db}.extracted_records "  # nosec B608
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
                f"FROM {self._db}.extracted_records "  # nosec B608
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
                    jwt_subject=_claim_str(claims, "sub"),
                    jwt_issuer=_claim_str(claims, "iss"),
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
                "       uniqHLL12((archive_sha256, victim_folder, file_path, "
                "                      cityHash64(toString(fields)))) AS hits, "
                "       min(ingested_at) AS first_hit, max(ingested_at) AS last_hit "
                f"FROM {self._db}.extracted_records "  # nosec B608
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
                rule_id=r[0],
                rule_name="",
                severity="info",
                hit_count=int(r[1] or 0),
                first_hit_at=r[2],
                last_hit_at=r[3],
            )
            for r in rows.result_rows
        ]
