"""Client-parity rule engine for stealer-log family detection and extraction.

Mirrors ``eyenet-fe/src/lib/stealer-engine/`` byte-for-byte on output.
Parity is enforced by golden fixtures in ``tests/fixtures/stealer_rules/``:
the same (rule, input) pair MUST yield the same extracted fields in Python
and the browser-side TypeScript engine.

Spec: ``development/STEALER_RULE_DSL.md``.
"""

from eyenet.stealer.rules.engine import RunResult, run_rules
from eyenet.stealer.rules.types import EvalResult

__all__ = ["EvalResult", "RunResult", "run_rules"]
