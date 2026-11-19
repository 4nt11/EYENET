# ruff: noqa: PLR2004, S101
"""Smoke parity with the JS _selftest.js. Run from repo root:

    python -m eyenet.stealer.rules._selftest

Mirrors every assertion in ``eyenet-fe/src/lib/stealer-engine/_selftest.js``
so a divergence between the engines shows up as the same assertion failing
on exactly one side. Dev tool, not part of prod import path: assertions
and verbatim JS-port lines are intentional.
"""

from __future__ import annotations

import json
import time
from typing import cast

from eyenet.stealer.rules.engine import match_glob, run_rules
from eyenet.stealer.rules.matchers import match_json, match_keyvalue_ini, match_regex, match_yaml
from eyenet.stealer.rules.normalize import apply_normalize
from eyenet.stealer.rules.types import ContentInput, RuleSpec, VictimFolder


def _eq(label: str, got: object, want: object) -> None:
    if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
        raise AssertionError(f"[{label}] got {got!r} want {want!r}")


def self_test() -> str:
    # 1. normalize verbs
    _eq(
        "strip",
        apply_normalize({"a": "  x  "}, [{"verb": "strip_whitespace", "field": "a"}]),
        {"a": "x"},
    )
    _eq("lower", apply_normalize({"a": "AB"}, [{"verb": "lowercase", "field": "a"}]), {"a": "ab"})
    _eq("upper", apply_normalize({"a": "ab"}, [{"verb": "uppercase", "field": "a"}]), {"a": "AB"})
    _eq(
        "trunc",
        apply_normalize({"a": "abcdef"}, [{"verb": "truncate", "field": "a", "max_len": 3}]),
        {"a": "abc"},
    )
    _eq(
        "int",
        apply_normalize({"a": "count: 42"}, [{"verb": "int_from_string", "field": "a"}]),
        {"a": 42},
    )
    _eq(
        "replace",
        apply_normalize(
            {"a": "a  b   c"},
            [{"verb": "replace_re2", "field": "a", "pattern": r"\s+", "replacement": " "}],
        ),
        {"a": "a b c"},
    )

    # 2. INI
    ini_hit = match_keyvalue_ini(
        {"type": "keyvalue_ini", "requires_sections": ["Hardware"]},
        {"keys": {"Hardware.HWID": "hwid", "Software.OS": "os"}},
        ContentInput(
            path="information.txt", text="[Hardware]\nHWID=ABC-123\n\n[Software]\nOS=Win10\n"
        ),
    )
    _eq("ini", ini_hit, {"hwid": "ABC-123", "os": "Win10"})

    # 3. JSON
    json_hit = match_json(
        {"type": "json", "requires_keys": ["HWID"]},
        {"paths": {"hwid": "$.HWID", "first": "$.Wallets[0].kind"}},
        ContentInput(path="pc_info.json", text='{"HWID":"X1","Wallets":[{"kind":"BTC"}]}'),
    )
    _eq("json", json_hit, {"hwid": "X1", "first": "BTC"})

    # 3b. YAML
    yaml_hit = match_yaml(
        {"type": "yaml", "requires_keys": ["Build"]},
        {"paths": {"build": "$.Build", "hwid": "$.HWID"}},
        ContentInput(path="info.yaml", text="Build: ACR-9.1\nHWID: Z2\n"),
    )
    _eq("yaml", yaml_hit, {"build": "ACR-9.1", "hwid": "Z2"})

    # 3c. RE2 matcher: named captures
    re_hit = match_regex(
        {"type": "regex", "pattern": r"HWID:\s*(?P<hwid>[A-Z0-9-]+)", "multiline": True},
        {"fields": ["hwid"]},
        ContentInput(path="x.txt", text="noise\nHWID: ABC-999\n"),
    )
    _eq("re2-hit", re_hit, {"hwid": "ABC-999"})

    # 3d. RE2 ReDoS safety
    t0 = time.monotonic()
    evil = match_regex(
        {"type": "regex", "pattern": r"^(a+)+$"},
        None,
        ContentInput(path="x", text="a" * 30 + "!"),
    )
    if time.monotonic() - t0 > 0.5:
        raise AssertionError("RE2 ReDoS guard failed: took too long")
    if evil is not None:
        raise AssertionError("RE2 match should have failed on bad input")

    # 4. glob
    assert match_glob("**/*.txt", "a/b/c.txt"), "glob should match"
    assert not match_glob("**/*.txt", "a/b/c.json"), "glob should not match"

    # 5. end-to-end
    rules = [
        {
            "id": "lumma_folder",
            "version": 1,
            "layer": "container",
            "family": "lumma",
            "priority": 100,
            "match": {"type": "folder", "requires": ["System.txt"]},
        },
        {
            "id": "lumma_system_txt",
            "version": 1,
            "layer": "content",
            "family": "lumma",
            "priority": 100,
            "path_glob": "System.txt",
            "match": {
                "type": "keyvalue",
                "separator": ":",
                "strip_whitespace": True,
                "requires_keys": ["HWID"],
            },
            "extract": {"keys": {"HWID": "hwid", "IP": "ip", "Country": "country"}},
            "normalize": [
                {"verb": "uppercase", "field": "hwid"},
                {"verb": "lowercase", "field": "country"},
            ],
        },
    ]
    folder = VictimFolder(
        root_name="victim-001",
        files=(
            ContentInput(
                path="System.txt", text="HWID: abc-123\nIP: 1.2.3.4\nCountry: US\n"
            ),  # pragma: allowlist secret
        ),
    )
    r = run_rules(cast("list[RuleSpec]", rules), folder)
    _eq("family", r.family, "lumma")
    _eq("merged", r.fields, {"hwid": "ABC-123", "ip": "1.2.3.4", "country": "us"})

    return "ok"


if __name__ == "__main__":
    print(self_test())
