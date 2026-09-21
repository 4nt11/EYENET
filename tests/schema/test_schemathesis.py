"""Schemathesis property-based fuzzing of the v1 surface.

Wired against `create_app()` (ASGI, no live server needed). Currently SKIPPED:
every endpoint is an M9.0 NotImplementedError stub → 501 ProblemDetail, which
does not match the documented 2xx/4xx responses. Running now would produce 35
spurious failures.

Re-enable in M9.3 (route handlers land) by deleting the module-level skip.

To run ad-hoc without removing the skip:
    pytest tests/schema/test_schemathesis.py -m schema --no-cov -p no:randomly --run-skipped
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
import schemathesis

from eyenet.api.app import create_app
from eyenet.storage.factory import get_repository

pytestmark = pytest.mark.schema

# Module-level skip: the body below has import-time side effects (from_asgi
# fetches the schema over ASGI), and since §12.5 gated /v1/openapi.json behind
# read:graph, an anonymous fetch now 401s at *collection* time. Skip before that
# runs. Re-enable in M9.3 by removing this skip AND giving from_asgi a read:graph
# bearer (or pointing it at an in-process app.openapi() dump).
pytest.skip(
    "M9.0 skeleton: every endpoint is a 501 stub; §12.5 also gated the schema. Re-enable at M9.3.",
    allow_module_level=True,
)


_storage = get_repository(in_memory=True)
_tmpdir = tempfile.mkdtemp(prefix="eyenet-schemathesis-")
_app = create_app(storage=_storage, data_dir=Path(_tmpdir))
schema = schemathesis.openapi.from_asgi("/v1/openapi.json", _app)


@schema.parametrize()
def test_api_conforms_to_openapi(case: schemathesis.Case[Any]) -> None:
    """Every generated request gets a response that matches the OpenAPI."""
    case.call_and_validate()
