"""Shared type contracts for the stealer rule DSL engine.

JS parity: ``eyenet-fe/src/lib/stealer-engine/types.js``.

Rule YAML is validated against a JSON Schema at load; the engine consumes
plain dicts here so the hot path pays no pydantic cost. The output types
(EvalResult, RunResult) are dataclasses for ergonomic callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

Layer = Literal["container", "content"]
RuleType = Literal[
    "folder", "regex", "delimiter", "template",
    "json", "yaml", "keyvalue", "keyvalue_ini",
]


class FolderMatch(TypedDict, total=False):
    type: Literal["folder"]
    requires: list[str]
    forbids: list[str]
    optional: list[str]
    min_score: int


class RegexMatch(TypedDict, total=False):
    type: Literal["regex"]
    pattern: str
    multiline: bool
    dotall: bool


class DelimiterMatch(TypedDict, total=False):
    type: Literal["delimiter"]
    separator: str
    min_columns: int
    skip_blank: bool
    skip_comment_prefix: str


class TemplateMatch(TypedDict, total=False):
    type: Literal["template"]
    template: str
    multiline: bool


class JsonMatch(TypedDict, total=False):
    type: Literal["json"]
    requires_keys: list[str]


class YamlMatch(TypedDict, total=False):
    type: Literal["yaml"]
    requires_keys: list[str]


class KeyvalueMatch(TypedDict, total=False):
    type: Literal["keyvalue"]
    separator: str
    strip_whitespace: bool
    requires_keys: list[str]


class KeyvalueIniMatch(TypedDict, total=False):
    type: Literal["keyvalue_ini"]
    requires_sections: list[str]


MatchSpec = (
    FolderMatch | RegexMatch | DelimiterMatch | TemplateMatch
    | JsonMatch | YamlMatch | KeyvalueMatch | KeyvalueIniMatch
)


class ExtractSpec(TypedDict, total=False):
    fields: list[str]
    columns: dict[int | str, str]
    paths: dict[str, str]
    keys: dict[str, str]


class MapSpec(TypedDict, total=False):
    _drop: list[str]
    rename: dict[str, str]


class NormalizeStep(TypedDict, total=False):
    verb: Literal[
        "strip_whitespace", "lowercase", "uppercase", "truncate",
        "int_from_string", "replace_re2", "date_parse",
    ]
    field: str
    max_len: int
    pattern: str
    replacement: str
    format: Literal["iso8601", "rfc2822", "epoch_seconds"]


class RuleSpec(TypedDict, total=False):
    id: str
    version: int
    layer: Layer
    family: str
    priority: int
    description: str
    path_glob: str
    requires_container_family: str  # content layer only; only fire when L1 winner family == this
    match: MatchSpec
    extract: ExtractSpec
    map: MapSpec
    reject_patterns: list[str]  # RE2 patterns tested against every extracted value
    normalize: list[NormalizeStep]


@dataclass(frozen=True, slots=True)
class ContentInput:
    """One file's bytes + its relative path inside the victim folder."""
    path: str
    text: str


@dataclass(frozen=True, slots=True)
class ContainerInput:
    """Just the list of relative paths found in a victim folder."""
    paths: tuple[str, ...]


@dataclass(slots=True)
class EvalResult:
    rule_id: str
    layer: Layer
    family: str
    priority: int
    matched: bool
    fields: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    file_path: str | None = None  # content-layer only; the file this evaluation ran against


@dataclass(slots=True)
class VictimFolder:
    root_name: str
    files: tuple[ContentInput, ...]
