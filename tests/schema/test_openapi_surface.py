"""§14.4 — FastAPI-generated OpenAPI ≡ hand-drafted YAML at the surface level.

We compare the two specs on the dimensions that govern client codegen and
Schemathesis fuzzing:

- Path x method set equality.
- Operation-ID set equality.
- Primary success status code per operation.
- Success-response schema $ref name per operation.
- Request-body schema $ref name per operation (when a body exists).
- `components/schemas` name set equality (modulo FastAPI's auto-generated
  helpers `HTTPValidationError`, `Body_*`, and `ValidationError` namespace
  collisions — see ALLOWED_GENERATED_EXTRAS below).

Deliberately NOT enforced (out of scope for skeleton tier):
- Per-field schema equality (defer to Schemathesis at M9.3).
- Per-operation 4xx/5xx response sets — the shared `responses=` on v1_router
  propagates them uniformly; the hand-drafted YAML enumerates them per op.
  Equivalence is structural, not literal.
- `x-eyenet-sse-events` extension on stream endpoints (FastAPI can't model SSE
  event shapes natively; the YAML carries them for documentation).
"""

from __future__ import annotations

from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from eyenet.api.app import create_app

pytestmark = pytest.mark.contract

# FastAPI auto-generates these even when we override 422 via exception handler.
# They are not in the hand-drafted YAML and we don't want them to be — they're
# implementation noise.
ALLOWED_GENERATED_EXTRAS = {
    "HTTPValidationError",
}

# Hand-drafted-only schemas — intentionally not in the FastAPI output:
# - SSE event payloads are documented via the `x-eyenet-sse-events` extension
#   on stream operations; FastAPI cannot model SSE event shapes natively.
# - CursorPageBase is a composition base (allOf source); FastAPI inlines.
# - NeighborEdge is a discriminated union; FastAPI exposes the variants directly.
# - PersonaSummary is a composition base for PersonaDetail; FastAPI inlines.
YAML_ONLY_SCHEMAS = {
    "AuditEvent",
    "ControlEvent",
    "LinkageProposedEvent",
    "LinkageStateChangedEvent",
    "PersonaUpdatedEvent",
    "StreamGapEvent",
    "CursorPageBase",
    "NeighborEdge",
    "PersonaSummary",
    # RedactionMarker is the §4.7 polymorphic-content replacement shape.
    # Defined in YAML and exists as a Pydantic class, but no operation's
    # response_model references it yet — the content-field retrofit
    # (`field: Original | RedactionMarker`) lands incrementally with the
    # sensitivity-aware handlers in M9.3. Until then it's a library schema
    # in the YAML, intentionally absent from FastAPI's generated output.
    "RedactionMarker",
}


@pytest.fixture(scope="module")
def hand() -> dict[str, Any]:
    with open("contracts/openapi/eyenet.v1.yaml", encoding="utf-8") as fh:
        return cast("dict[str, Any]", yaml.safe_load(fh))


@pytest.fixture(scope="module")
def gen() -> dict[str, Any]:
    import tempfile
    from pathlib import Path

    from eyenet.storage.factory import get_repository

    storage = get_repository(in_memory=True)
    with tempfile.TemporaryDirectory() as td:
        client = TestClient(create_app(storage=storage, data_dir=Path(td)))
        resp = client.get("/v1/openapi.json")
    assert resp.status_code == 200
    return cast("dict[str, Any]", resp.json())


def _operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (path, method.upper()): op
        for path, methods in spec["paths"].items()
        for method, op in methods.items()
        if method in {"get", "post", "put", "delete", "patch"}
    }


def _primary_success(op: dict[str, Any]) -> str | None:
    for code in op.get("responses", {}):
        if str(code).startswith("2"):
            return str(code)
    return None


def _resolve_response_ref(spec: dict[str, Any], resp: dict[str, Any]) -> dict[str, Any]:
    """If `resp` is a $ref to components/responses/X, return the resolved object."""
    if "$ref" in resp:
        name = resp["$ref"].split("/")[-1]
        return cast("dict[str, Any]", spec.get("components", {}).get("responses", {}).get(name, {}))
    return resp


def _success_schema_ref(spec: dict[str, Any], op: dict[str, Any]) -> str | None:
    code = _primary_success(op)
    if code is None:
        return None
    resp = _resolve_response_ref(spec, op["responses"][code])
    content = resp.get("content", {})
    for body in content.values():
        s = body.get("schema", {})
        if "$ref" in s:
            return cast("str", s["$ref"].split("/")[-1])
    return None  # streaming or no-body responses


def _request_body_ref(op: dict[str, Any]) -> str | None:
    rb = op.get("requestBody", {})
    if not rb:
        return None
    for body in rb.get("content", {}).values():
        s = body.get("schema", {})
        if "$ref" in s:
            return cast("str", s["$ref"].split("/")[-1])
    return None


def test_path_method_set_equality(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    assert set(_operations(hand).keys()) == set(_operations(gen).keys())


def test_operation_id_set_equality(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    h_ops = {op["operationId"] for op in _operations(hand).values()}
    g_ops = {op["operationId"] for op in _operations(gen).values()}
    assert h_ops == g_ops


def test_primary_success_status_codes_match(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    h_ops = _operations(hand)
    g_ops = _operations(gen)
    mismatches = []
    for key, h_op in h_ops.items():
        g_op = g_ops[key]
        h_code = _primary_success(h_op)
        g_code = _primary_success(g_op)
        if h_code != g_code:
            mismatches.append((key, h_code, g_code))
    assert not mismatches, f"success-code drift: {mismatches}"


def test_success_response_schema_refs_match(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    h_ops = _operations(hand)
    g_ops = _operations(gen)
    mismatches = []
    for key, h_op in h_ops.items():
        g_op = g_ops[key]
        h_ref = _success_schema_ref(hand, h_op)
        g_ref = _success_schema_ref(gen, g_op)
        if h_ref != g_ref:
            mismatches.append((key, h_ref, g_ref))
    assert not mismatches, f"success-schema drift: {mismatches}"


def test_request_body_schema_refs_match(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    h_ops = _operations(hand)
    g_ops = _operations(gen)
    mismatches = []
    for key, h_op in h_ops.items():
        g_op = g_ops[key]
        h_ref = _request_body_ref(h_op)
        g_ref = _request_body_ref(g_op)
        if h_ref != g_ref:
            mismatches.append((key, h_ref, g_ref))
    assert not mismatches, f"request-body schema drift: {mismatches}"


def test_components_schemas_name_equality(hand: dict[str, Any], gen: dict[str, Any]) -> None:
    h_schemas = set(hand.get("components", {}).get("schemas", {}).keys())
    g_schemas = set(gen.get("components", {}).get("schemas", {}).keys())
    extras = g_schemas - h_schemas - ALLOWED_GENERATED_EXTRAS
    missing = h_schemas - g_schemas - YAML_ONLY_SCHEMAS
    assert not missing, f"hand-drafted schemas missing from FastAPI output: {sorted(missing)}"
    assert not extras, f"FastAPI generated unexpected schemas: {sorted(extras)}"
