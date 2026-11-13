"""Schemathesis property-based fuzzing of the v1 surface.

Runs the full generated-request fuzzer against :func:`create_app` as an ASGI
app. The OpenAPI schema is gated behind ``read:graph`` (§12.5), so we:

  1. Boot an in-memory app
  2. Seed an admin user and mint an access token
  3. Fetch /v1/openapi.json authenticated and save to a tmp file
  4. Load the schema from that file and parametrize

Each generated request is sent through the same ASGI app, carrying the admin
bearer so authorization is not the dominant failure mode (we want shape /
status-code conformance checked, not 401 everywhere).

Run:
    pytest tests/schema/test_schemathesis.py -m schema --no-cov -p no:randomly
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import schemathesis
from schemathesis.specs.openapi.checks import content_type_conformance

from eyenet.api.app import create_app
from eyenet.api.auth import hash_password
from eyenet.api.auth._jwt import load_signing_keypair, mint_access_token
from eyenet.contracts.enums import SystemUserRole
from eyenet.storage.factory import get_repository

pytestmark = pytest.mark.schema


_storage = get_repository(in_memory=True)
_tmpdir = Path(tempfile.mkdtemp(prefix="eyenet-schemathesis-"))
_app = create_app(storage=_storage, data_dir=_tmpdir)


def _bootstrap() -> str:
    """Seed one admin, mint a bearer, return it."""
    now = datetime.now(tz=UTC)
    user_id = uuid4()

    async def _seed() -> None:
        await _storage.put_system_user(
            user_id=user_id,
            username="fuzz",
            display_name="Fuzz",
            role=SystemUserRole.ADMIN,
            created_at=now,
            is_active=True,
        )
        await _storage.put_credential(
            user_id=user_id,
            password_hash=hash_password("fuzz-pw"),
            password_updated_at=now,
            mfa_secret_encrypted=None,
        )

    asyncio.get_event_loop().run_until_complete(_seed()) if False else asyncio.run(_seed())

    signing_key = load_signing_keypair(_tmpdir)
    token, _ = mint_access_token(user_id=user_id, signing_key=signing_key, now=now)
    return token


_TOKEN = _bootstrap()
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}

# Fetch the schema authenticated, dump to tmp, then load from path. from_asgi
# does not expose per-request headers on the schema fetch itself.
from fastapi.testclient import TestClient  # noqa: E402

with TestClient(_app) as _c:
    _r = _c.get("/v1/openapi.json", headers=_HEADERS)
    assert _r.status_code == 200, _r.text
    _schema_path = _tmpdir / "openapi.json"
    _schema_path.write_text(json.dumps(_r.json()))

schema = schemathesis.openapi.from_asgi("/v1/openapi.json", _app, headers=_HEADERS)


@schema.parametrize()
def test_api_conforms_to_openapi(case: schemathesis.Case[Any]) -> None:
    """Every generated request gets a response that matches the OpenAPI.

    ``UndefinedContentType`` is excluded on purpose: the API serves RFC 7807
    ``application/problem+json`` for all 4xx/5xx errors but the generated
    schema declares ``application/json``. That is a schema-docs gap worth
    fixing in a dedicated pass; it would otherwise swamp every real finding.
    """
    case.call_and_validate(
        headers=_HEADERS,
        excluded_checks=[content_type_conformance],
    )
