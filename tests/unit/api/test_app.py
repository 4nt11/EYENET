"""App-build smoke tests for the M9.0 FastAPI skeleton.

Covers:
- create_app() returns a FastAPI instance with every documented v1 path mounted.
- NotImplementedError handler returns 501 with application/problem+json + valid
  ProblemDetail envelope.
- RequestValidationError handler returns 422 with application/problem+json + the
  populated `errors[]` rows.
- OpenAPI is generated at /v1/openapi.json and includes every operation_id.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from eyenet.api.app import PROBLEM_JSON, create_app

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def hand_drafted_spec() -> dict[str, Any]:
    with open("contracts/openapi/eyenet.v1.yaml", encoding="utf-8") as fh:
        return cast("dict[str, Any]", yaml.safe_load(fh))


def test_app_serves_openapi(client: TestClient) -> None:
    resp = client.get("/v1/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["openapi"].startswith("3.")
    assert "/v1/auth/login" in spec["paths"]


def test_every_documented_path_is_registered(
    client: TestClient, hand_drafted_spec: dict[str, Any]
) -> None:
    resp = client.get("/v1/openapi.json")
    generated = resp.json()

    def _surface(spec: dict[str, Any]) -> set[tuple[str, str]]:
        return {
            (path, method.upper())
            for path, methods in spec["paths"].items()
            for method in methods
            if method in {"get", "post", "put", "delete", "patch"}
        }

    hand = _surface(hand_drafted_spec)
    gen = _surface(generated)
    missing = hand - gen
    extra = gen - hand
    assert not missing, f"endpoints in YAML but not registered: {sorted(missing)}"
    assert not extra, f"endpoints registered but not in YAML: {sorted(extra)}"


def test_every_operation_id_present(client: TestClient, hand_drafted_spec: dict[str, Any]) -> None:
    resp = client.get("/v1/openapi.json")
    generated = resp.json()

    def _op_ids(spec: dict[str, Any]) -> set[str]:
        return {
            op["operationId"]
            for methods in spec["paths"].values()
            for method, op in methods.items()
            if method in {"get", "post", "put", "delete", "patch"}
        }

    assert _op_ids(hand_drafted_spec) == _op_ids(generated)


def test_not_implemented_returns_problem_json(client: TestClient) -> None:
    resp = client.get("/v1/healthz")
    assert resp.status_code == 501
    assert resp.headers["content-type"].startswith(PROBLEM_JSON)
    body = resp.json()
    assert body["status"] == 501
    assert body["title"] == "Not Implemented"
    assert body["instance"] == "/v1/healthz"
    assert "request_id" in body


def test_request_id_header_is_propagated(client: TestClient) -> None:
    rid = "test-request-id-7777"
    resp = client.get("/v1/healthz", headers={"X-Request-Id": rid})
    body = resp.json()
    assert body["request_id"] == rid


def test_validation_error_returns_problem_json(client: TestClient) -> None:
    resp = client.post("/v1/auth/login", json={"username": "anti"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith(PROBLEM_JSON)
    body = resp.json()
    assert body["status"] == 422
    assert body["title"] == "Validation Failed"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) >= 1
    err = body["errors"][0]
    assert "loc" in err and "msg" in err and "type" in err


def test_validation_error_rejects_extra_field(client: TestClient) -> None:
    resp = client.post(
        "/v1/auth/login",
        json={"username": "anti", "password": "p", "rogue": "x"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert any("rogue" in str(err["loc"]) for err in body["errors"])
