# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /v1/stealer/by-domain/{domain}/* - Domain View endpoints (read:stealer).

Reverse-lookup surface keyed on a domain. Operator picks a domain, lands on a
single page that answers everything we know about it. One router, 8 routes,
one reader: ``DomainCorpusReader`` in ``eyenet.stealer.query_by_domain``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from eyenet.api.deps import CurrentUser, RequireScope
from eyenet.api.v1.schemas.by_domain import (
    DomainAutofillRow,
    DomainAutofillsResponse,
    DomainCookieRow,
    DomainCookiesResponse,
    DomainCredRow,
    DomainCredsResponse,
    DomainHistoryResponse,
    DomainHistoryRow,
    DomainIndicatorRow,
    DomainIndicatorsResponse,
    DomainSubdomainRow,
    DomainSubdomainsResponse,
    DomainSummary,
    DomainVictimRow,
    DomainVictimsResponse,
)
from eyenet.stealer.query_by_domain import (
    DomainCorpusReader,
    StealerCorpusUninitializedError,
    canonicalize,
)

router = APIRouter(tags=["stealer"])
_reader = DomainCorpusReader()

_DomainParam = Annotated[
    str,
    Path(
        min_length=1,
        max_length=253,
        description="Domain or registrable suffix; URL-encoded. Canonicalised server-side.",
    ),
]


def _pages(total: int, limit: int) -> int:
    return (total + limit - 1) // limit if total else 0


def _bail(exc: Exception) -> None:
    """Shared 503 for any underlying CH blow-up."""
    raise HTTPException(status_code=503, detail=f"stealer corpus unavailable: {exc}") from exc


@router.get(
    "/stealer/by-domain/{domain}/summary",
    operation_id="stealer_by_domain_summary",
    response_model=DomainSummary,
    status_code=200,
)
async def by_domain_summary(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
) -> DomainSummary:
    canonical = canonicalize(domain)
    try:
        s = await _reader.summary(canonical)
    except StealerCorpusUninitializedError:
        return DomainSummary(
            raw_domain=domain, canonical_domain=canonical,
            victim_count=0, archive_count=0,
            first_seen_at=None, last_seen_at=None,
            credential_count=0, live_cookie_count=0, all_cookie_count=0,
            autofill_count=0, history_count=0, localstorage_jwt_count=0,
            indicator_hit_count=0, reindex_in_flight=False,
        )
    except Exception as exc:
        _bail(exc)
    return DomainSummary(
        raw_domain=domain,
        canonical_domain=s.canonical_domain,
        victim_count=s.victim_count,
        archive_count=s.archive_count,
        first_seen_at=s.first_seen_at,
        last_seen_at=s.last_seen_at,
        credential_count=s.credential_count,
        live_cookie_count=s.live_cookie_count,
        all_cookie_count=s.all_cookie_count,
        autofill_count=s.autofill_count,
        history_count=s.history_count,
        localstorage_jwt_count=s.localstorage_jwt_count,
        indicator_hit_count=s.indicator_hit_count,
        # TODO: wire bus-state cache. False until the summary cache hook lands.
        reindex_in_flight=False,
    )


@router.get(
    "/stealer/by-domain/{domain}/credentials",
    operation_id="stealer_by_domain_credentials",
    response_model=DomainCredsResponse,
    status_code=200,
)
async def by_domain_credentials(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> DomainCredsResponse:
    offset = (page - 1) * limit
    try:
        rows, total = await _reader.credentials(
            canonical=canonicalize(domain), limit=limit, offset=offset
        )
    except StealerCorpusUninitializedError:
        return DomainCredsResponse(items=[], total=0, pages=0)
    except Exception as exc:
        _bail(exc)
    return DomainCredsResponse(
        items=[
            DomainCredRow(
                host=r.host, url=r.url, login=r.login, password=r.password,
                scheme=r.scheme, archive_sha256=r.archive_sha256,
                victim_folder=r.victim_folder, ingested_at=r.ingested_at,
            )
            for r in rows
        ],
        total=total, pages=_pages(total, limit),
    )


@router.get(
    "/stealer/by-domain/{domain}/victims",
    operation_id="stealer_by_domain_victims",
    response_model=DomainVictimsResponse,
    status_code=200,
)
async def by_domain_victims(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> DomainVictimsResponse:
    offset = (page - 1) * limit
    try:
        rows, total = await _reader.victims(
            canonical=canonicalize(domain), limit=limit, offset=offset
        )
    except StealerCorpusUninitializedError:
        return DomainVictimsResponse(items=[], total=0, pages=0)
    except Exception as exc:
        _bail(exc)
    return DomainVictimsResponse(
        items=[
            DomainVictimRow(
                archive_sha256=r.archive_sha256, victim_folder=r.victim_folder,
                country=r.country, build_version=r.build_version,
                credential_count=r.credential_count, cookie_count=r.cookie_count,
                first_seen_at=r.first_seen_at,
            )
            for r in rows
        ],
        total=total, pages=_pages(total, limit),
    )


@router.get(
    "/stealer/by-domain/{domain}/subdomains",
    operation_id="stealer_by_domain_subdomains",
    response_model=DomainSubdomainsResponse,
    status_code=200,
)
async def by_domain_subdomains(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DomainSubdomainsResponse:
    try:
        rows, total = await _reader.subdomains(canonical=canonicalize(domain), limit=limit)
    except StealerCorpusUninitializedError:
        return DomainSubdomainsResponse(items=[], total=0)
    except Exception as exc:
        _bail(exc)
    return DomainSubdomainsResponse(
        items=[
            DomainSubdomainRow(
                host=r.host, credential_count=r.credential_count,
                cookie_count=r.cookie_count,
            )
            for r in rows
        ],
        total=total,
    )


@router.get(
    "/stealer/by-domain/{domain}/cookies",
    operation_id="stealer_by_domain_cookies",
    response_model=DomainCookiesResponse,
    status_code=200,
)
async def by_domain_cookies(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    live_only: Annotated[bool, Query()] = False,
) -> DomainCookiesResponse:
    offset = (page - 1) * limit
    try:
        rows, total = await _reader.cookies(
            canonical=canonicalize(domain), limit=limit, offset=offset, live_only=live_only,
        )
    except StealerCorpusUninitializedError:
        return DomainCookiesResponse(items=[], total=0, pages=0)
    except Exception as exc:
        _bail(exc)
    return DomainCookiesResponse(
        items=[
            DomainCookieRow(
                host=r.host, name=r.name, value=r.value, expires_at=r.expires_at,
                http_only=r.http_only, secure=r.secure,
                archive_sha256=r.archive_sha256, victim_folder=r.victim_folder,
            )
            for r in rows
        ],
        total=total, pages=_pages(total, limit),
    )


@router.get(
    "/stealer/by-domain/{domain}/autofills",
    operation_id="stealer_by_domain_autofills",
    response_model=DomainAutofillsResponse,
    status_code=200,
)
async def by_domain_autofills(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> DomainAutofillsResponse:
    offset = (page - 1) * limit
    try:
        rows, total = await _reader.autofills(
            canonical=canonicalize(domain), limit=limit, offset=offset,
        )
    except StealerCorpusUninitializedError:
        return DomainAutofillsResponse(items=[], total=0, pages=0)
    except Exception as exc:
        _bail(exc)
    return DomainAutofillsResponse(
        items=[
            DomainAutofillRow(
                host=r.host, field_name=r.field_name, value=r.value,
                archive_sha256=r.archive_sha256, victim_folder=r.victim_folder,
            )
            for r in rows
        ],
        total=total, pages=_pages(total, limit),
    )


@router.get(
    "/stealer/by-domain/{domain}/history",
    operation_id="stealer_by_domain_history",
    response_model=DomainHistoryResponse,
    status_code=200,
)
async def by_domain_history(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> DomainHistoryResponse:
    offset = (page - 1) * limit
    try:
        rows, total = await _reader.history(
            canonical=canonicalize(domain), limit=limit, offset=offset,
        )
    except StealerCorpusUninitializedError:
        return DomainHistoryResponse(items=[], total=0, pages=0)
    except Exception as exc:
        _bail(exc)
    return DomainHistoryResponse(
        items=[
            DomainHistoryRow(
                host=r.host, url=r.url, title=r.title,
                visit_count=r.visit_count, last_visit_at=r.last_visit_at,
                archive_sha256=r.archive_sha256, victim_folder=r.victim_folder,
            )
            for r in rows
        ],
        total=total, pages=_pages(total, limit),
    )


@router.get(
    "/stealer/by-domain/{domain}/indicators",
    operation_id="stealer_by_domain_indicators",
    response_model=DomainIndicatorsResponse,
    status_code=200,
)
async def by_domain_indicators(
    _: Annotated[CurrentUser, Depends(RequireScope("read:stealer"))],
    domain: _DomainParam,
) -> DomainIndicatorsResponse:
    try:
        rows = await _reader.indicators(canonicalize(domain))
    except StealerCorpusUninitializedError:
        return DomainIndicatorsResponse(items=[], total=0)
    except Exception as exc:
        _bail(exc)
    # rule_name + severity default to "" / "info" in the reader; a follow-up
    # patch can enrich from the operator rule catalog without changing the
    # endpoint contract (DTO already carries both fields).
    return DomainIndicatorsResponse(
        items=[
            DomainIndicatorRow(
                rule_id=r.rule_id, rule_name=r.rule_name, severity=r.severity,
                hit_count=r.hit_count, first_hit_at=r.first_hit_at, last_hit_at=r.last_hit_at,
            )
            for r in rows
        ],
        total=len(rows),
    )
