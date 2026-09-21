# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenAPI surface of `/v1/auth/login` carries the discriminated oneOf."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.integration


def test_login_response_is_one_of_token_pair_and_mfa_challenge(app: FastAPI) -> None:
    # /v1/openapi.json is read:graph-gated (§12.5); read the schema in-process.
    spec = app.openapi()
    login_resp = spec["paths"]["/v1/auth/login"]["post"]["responses"]["200"]
    schema = login_resp["content"]["application/json"]["schema"]
    assert "oneOf" in schema, schema
    refs = {item.get("$ref") for item in schema["oneOf"]}
    assert "#/components/schemas/TokenPair" in refs
    assert "#/components/schemas/MfaLoginChallenge" in refs
    discriminator = schema.get("discriminator", {})
    assert discriminator.get("propertyName") == "kind"


def test_login_verify_returns_token_pair_schema(app: FastAPI) -> None:
    spec = app.openapi()
    op = spec["paths"]["/v1/auth/login/verify"]["post"]
    body = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["$ref"] == "#/components/schemas/TokenPair"
