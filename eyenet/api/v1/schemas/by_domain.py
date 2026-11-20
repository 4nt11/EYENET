# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared DTOs for the Domain View surface (/v1/stealer/by-domain/{domain}/*).

Shipped BEFORE the handler code so backend and frontend can work in parallel
against a frozen contract. The handlers import these, the FE consumes them
via the OpenAPI schema. Changes here are contract changes, not refactors.

All endpoints require the ``read:stealer`` scope.
"""

from __future__ import annotations

from datetime import datetime

from ._base import ApiSchema


class DomainSummary(ApiSchema):
    """Hero card. All counts are de-duplicated at the (archive, victim_folder,
    rule_id, file_path, fields-hash) identity tuple. ``raw_domain`` is the
    operator's input; ``canonical_domain`` is the registrable form we actually
    queried (e.g. ``www.test.com`` -> ``test.com``). Dates are ISO 8601 UTC.
    """

    raw_domain: str
    canonical_domain: str
    victim_count: int
    archive_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    credential_count: int
    live_cookie_count: int  # cookies with expires > now()
    all_cookie_count: int
    autofill_count: int
    history_count: int
    localstorage_jwt_count: int
    indicator_hit_count: int
    reindex_in_flight: bool


class DomainCredRow(ApiSchema):
    host: str
    url: str
    login: str
    password: str
    scheme: str
    archive_sha256: str
    victim_folder: str
    ingested_at: datetime


class DomainCredsResponse(ApiSchema):
    items: list[DomainCredRow]
    total: int
    pages: int


class DomainVictimRow(ApiSchema):
    archive_sha256: str
    victim_folder: str
    country: str
    build_version: str
    credential_count: int
    cookie_count: int
    first_seen_at: datetime | None
    # v1.3.7 addition: the installer MD5 that put the stealer on this
    # machine. Populated only when a userinfo_*_shape rule captured
    # fields['ui_payload_md5'] during extraction (26% of victims on prod
    # today; see /v1/stealer/rule-coverage-gaps for the gap). Null when
    # no fingerprint rule fired for this victim. Operators copy this
    # directly into SIEM / EDR as a blocking IOC.
    loader_md5: str | None = None


class DomainVictimsResponse(ApiSchema):
    items: list[DomainVictimRow]
    total: int
    pages: int


class DomainSubdomainRow(ApiSchema):
    """One subdomain under the registrable domain, with its own slice counts."""

    host: str
    credential_count: int
    cookie_count: int


class DomainSubdomainsResponse(ApiSchema):
    items: list[DomainSubdomainRow]
    total: int  # unpaginated count of distinct subdomains


class DomainCookieRow(ApiSchema):
    host: str
    name: str
    value: str
    expires_at: datetime | None  # null for session cookies
    http_only: bool
    secure: bool
    archive_sha256: str
    victim_folder: str


class DomainCookiesResponse(ApiSchema):
    items: list[DomainCookieRow]
    total: int
    pages: int


class DomainAutofillRow(ApiSchema):
    host: str
    field_name: str
    value: str
    archive_sha256: str
    victim_folder: str


class DomainAutofillsResponse(ApiSchema):
    items: list[DomainAutofillRow]
    total: int
    pages: int


class DomainHistoryRow(ApiSchema):
    host: str
    url: str
    title: str
    visit_count: int
    last_visit_at: datetime | None
    archive_sha256: str
    victim_folder: str


class DomainHistoryResponse(ApiSchema):
    items: list[DomainHistoryRow]
    total: int
    pages: int


class DomainLocalStorageJwtRow(ApiSchema):
    """One leaked JWT stored in a victim's browser localStorage for this domain.

    Different pivot axis from credentials: a credential pair behind MFA/SSO is
    often moderate risk; a live-exp JWT IS the session and skips the MFA
    challenge entirely. Operators should triage by `is_expired` + `expires_at`.
    """

    host: str                       # display host (may carry scheme if the stealer did)
    key: str                        # localStorage key name (e.g. 'access_token')
    jwt_value: str                  # raw JWT; FE truncates for display
    jwt_subject: str | None         # decoded 'sub' claim (email/username)
    jwt_issuer: str | None          # decoded 'iss' claim
    jwt_audience: str | None        # decoded 'aud' claim
    jwt_algorithm: str | None       # decoded 'alg' from header
    expires_at: datetime | None     # decoded 'exp' claim
    is_expired: bool                # expires_at < now(); null-exp is treated as expired
    archive_sha256: str
    victim_folder: str


class DomainLocalStorageResponse(ApiSchema):
    items: list[DomainLocalStorageJwtRow]
    total: int
    pages: int
    live_count: int                 # non-expired JWTs in this page's domain match
    # ^ answer to "do we have any active sessions here?"; checks the FULL match
    # set not just this page, so an operator sees "3 live, 97 expired" at a glance.


class DomainIndicatorRow(ApiSchema):
    """One indicator rule that fired against this domain.

    Rule catalog is operator-authored so ``severity`` is the string the catalog
    carries (e.g. ``info``, ``low``, ``medium``, ``high``, ``critical``);
    callers should treat unknown values as ``info``.
    """

    rule_id: str
    rule_name: str
    severity: str
    hit_count: int
    first_hit_at: datetime | None
    last_hit_at: datetime | None


class DomainIndicatorsResponse(ApiSchema):
    items: list[DomainIndicatorRow]
    total: int  # unpaginated count; usually small (operators run O(10s) of rules)
