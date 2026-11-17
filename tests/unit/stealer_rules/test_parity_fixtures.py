"""Golden fixture parity: the Python engine must produce byte-identical
output to the browser-side JS engine for every fixture in
``tests/fixtures/stealer_rules/``.

The JS half of this parity test lives at
``eyenet-fe/tests/stealer-engine.parity.mjs`` and consumes the SAME
rule.yaml + input + expected.json files. Both harnesses must agree on
the computed ``RunResult`` for every fixture, or the build fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eyenet.stealer.rules.engine import run_rules
from eyenet.stealer.rules.types import ContentInput, VictimFolder

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "stealer_rules"


def _load_fixture(fdir: Path):
    rule = yaml.safe_load((fdir / "rule.yaml").read_text(encoding="utf-8"))
    expected = json.loads((fdir / "expected.json").read_text(encoding="utf-8"))
    input_files = [p for p in fdir.iterdir() if p.name.startswith("input.")]
    assert len(input_files) == 1, f"{fdir.name}: expected exactly one input.* file"
    file_path = rule.get("path_glob") or input_files[0].name
    text = input_files[0].read_text(encoding="utf-8")
    return rule, expected, ContentInput(path=file_path, text=text)


@pytest.mark.parametrize(
    "fixture_id",
    sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()),
)
def test_fixture_matches_expected(fixture_id: str) -> None:
    fdir = FIXTURES / fixture_id
    rule, expected, content = _load_fixture(fdir)
    folder = VictimFolder(root_name=fixture_id, files=(content,))
    result = run_rules([rule], folder)

    actual = {"family": result.family, "fields": result.fields}
    # Round-trip through JSON so int/float/bool normalization matches what
    # the JS harness will compare against.
    assert json.loads(json.dumps(actual, sort_keys=True)) == json.loads(
        json.dumps(expected, sort_keys=True)
    ), f"fixture {fixture_id} diverged\nactual:   {actual}\nexpected: {expected}"
