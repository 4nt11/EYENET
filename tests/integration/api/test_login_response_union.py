# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenAPI surface of `/v1/auth/login` carries the discriminated oneOf."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_login_response_is_one_of_token_pair_and_mfa_challenge(client: TestClient) -> None:
    spec = client.get("/v1/openapi.json").json()
    login_resp = spec["paths"]["/v1/auth/login"]["post"]["responses"]["200"]
    schema = login_resp["content"]["application/json"]["schema"]
    assert "oneOf" in schema, schema
    refs = {item.get("$ref") for item in schema["oneOf"]}
    assert "#/components/schemas/TokenPair" in refs
    assert "#/components/schemas/MfaLoginChallenge" in refs
    discriminator = schema.get("discriminator", {})
    assert discriminator.get("propertyName") == "kind"


def test_login_verify_returns_token_pair_schema(client: TestClient) -> None:
    spec = client.get("/v1/openapi.json").json()
    op = spec["paths"]["/v1/auth/login/verify"]["post"]
    body = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["$ref"] == "#/components/schemas/TokenPair"
