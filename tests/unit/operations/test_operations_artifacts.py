# SPDX-License-Identifier: AGPL-3.0-or-later
"""M9.6 slice 5 — the operations/ artifacts are well-formed and reference the
real metric names (a typo'd expr is a silent monitoring gap)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_OPS = Path(__file__).resolve().parents[3] / "operations"


def test_dashboard_is_valid_json_with_panels() -> None:
    dash = json.loads((_OPS / "dashboards" / "eyenet-api.json").read_text())
    assert dash["title"]
    assert dash["panels"]
    exprs = " ".join(
        t["expr"] for p in dash["panels"] for t in p.get("targets", []) if "expr" in t
    )
    for metric in ("eyenet_api_requests_total", "eyenet_api_healthy", "eyenet_api_sse_connections"):
        assert metric in exprs


def test_alert_rules_valid_and_reference_sli_metrics() -> None:
    rules = yaml.safe_load((_OPS / "alerts" / "eyenet-api.rules.yml").read_text())
    alerts = {r["alert"]: r["expr"] for g in rules["groups"] for r in g["rules"]}
    assert "EyenetAuditPublishFailures" in alerts
    assert "eyenet_api_audit_publish_failures_total" in alerts["EyenetAuditPublishFailures"]
    assert "eyenet_api_trace_propagation_missing_total" in alerts["EyenetTracePropagationMissing"]


def test_collector_config_has_tail_sampling() -> None:
    cfg = yaml.safe_load((_OPS / "otel-collector.sample.yaml").read_text())
    assert "tail_sampling" in cfg["processors"]
    assert cfg["service"]["pipelines"]["traces"]["processors"][0] == "tail_sampling"


def test_promtool_check_rules_if_available() -> None:
    promtool = shutil.which("promtool")
    if promtool is None:
        pytest.skip("promtool not on PATH")
    result = subprocess.run(  # noqa: S603 — fixed binary, fixed repo path
        [promtool, "check", "rules", str(_OPS / "alerts" / "eyenet-api.rules.yml")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
