"""advise(): orchestration — generate, repair, retry, bound, fail-soft.

Driven against a fake BaseProvider (the abstraction IS the test seam — no httpx,
no daemon). Covers the happy path, repair-then-retry, exhaustion, the
no-retry-on-unavailable vs retry-on-timeout split, input truncation, the egress
guard, and the no-echo property of the corrective re-prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from eyenet.classifier.llm import (
    LlmAdvisory,
    LlmConfig,
    LlmUnavailable,
    Msg,
    ProviderTimeoutError,
    ProviderUnavailableError,
    _advise as advise_mod,
    advise,
)

pytestmark = pytest.mark.unit

_GOOD = (
    '{"suggested_tier": "restricted", "summary": "memo", "indicators": ["a"], "confidence": "high"}'
)


class FakeProvider:
    """Scripts a sequence of generate() outcomes (str responses or exceptions)."""

    def __init__(
        self,
        responses: Sequence[object],
        *,
        is_local: bool = True,
        model: str = "fake-model",
    ) -> None:
        self._responses = list(responses)
        self._is_local = is_local
        self._model = model
        self.calls: list[tuple[Msg, ...]] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def is_local(self) -> bool:
        return self._is_local

    async def generate(
        self, messages: Sequence[Msg], *, json_schema: dict[str, object], timeout_s: float
    ) -> str:
        self.calls.append(tuple(messages))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def _cfg(**over: object) -> LlmConfig:
    base: dict[str, object] = {
        "config_version": "t",
        "model": "m",
        "endpoint": "http://127.0.0.1:11434",
        "connect_timeout_s": 1.0,
        "request_timeout_s": 1.0,
        "max_attempts": 3,
        "max_text_chars": 1000,
        "max_summary_chars": 200,
        "max_indicators": 5,
        "allow_remote": False,
    }
    base.update(over)
    return LlmConfig(**base)  # type: ignore[arg-type]


async def test_clean_first_try() -> None:
    fake = FakeProvider([_GOOD])
    out = await advise("doc", provider=fake, cfg=_cfg())
    assert isinstance(out, LlmAdvisory)
    assert out.attempts == 1
    assert out.model == "fake-model"  # provider-reported, filled by advise
    assert len(fake.calls) == 1


async def test_repair_then_success_on_second_attempt() -> None:
    fake = FakeProvider(["not json at all", _GOOD])
    out = await advise("doc", provider=fake, cfg=_cfg())
    assert isinstance(out, LlmAdvisory)
    assert out.attempts == 2
    assert len(fake.calls) == 2


async def test_exhausted_retries_is_unavailable() -> None:
    fake = FakeProvider(["nope", "still nope", "nope again"])
    out = await advise("doc", provider=fake, cfg=_cfg(max_attempts=3))
    assert isinstance(out, LlmUnavailable)
    assert out.reason == "unparseable_after_retries"
    assert out.attempts == 3
    assert len(fake.calls) == 3


async def test_provider_unavailable_does_not_retry() -> None:
    fake = FakeProvider([ProviderUnavailableError("connection refused"), _GOOD])
    out = await advise("doc", provider=fake, cfg=_cfg())
    assert isinstance(out, LlmUnavailable)
    assert out.reason == "provider_unavailable"
    assert out.attempts == 1
    assert len(fake.calls) == 1  # the daemon is down — re-prompting is pointless


async def test_timeout_is_retried_then_succeeds() -> None:
    fake = FakeProvider([ProviderTimeoutError("slow"), _GOOD])
    out = await advise("doc", provider=fake, cfg=_cfg())
    assert isinstance(out, LlmAdvisory)
    assert out.attempts == 2
    assert len(fake.calls) == 2


async def test_all_timeouts_exhaust_as_timeout() -> None:
    fake = FakeProvider([ProviderTimeoutError("x")] * 3)
    out = await advise("doc", provider=fake, cfg=_cfg(max_attempts=3))
    assert isinstance(out, LlmUnavailable)
    assert out.reason == "timeout"


async def test_input_is_truncated_and_flagged() -> None:
    fake = FakeProvider([_GOOD])
    out = await advise("x" * 500, provider=fake, cfg=_cfg(max_text_chars=10))
    assert isinstance(out, LlmAdvisory)
    assert out.truncated_input is True


async def test_short_input_not_flagged_truncated() -> None:
    fake = FakeProvider([_GOOD])
    out = await advise("short", provider=fake, cfg=_cfg(max_text_chars=1000))
    assert isinstance(out, LlmAdvisory)
    assert out.truncated_input is False


async def test_egress_guard_blocks_remote_when_disallowed() -> None:
    fake = FakeProvider([_GOOD], is_local=False)
    out = await advise("doc", provider=fake, cfg=_cfg(allow_remote=False))
    assert isinstance(out, LlmUnavailable)
    assert out.reason == "remote_not_allowed"
    assert out.attempts == 0
    assert len(fake.calls) == 0  # text never left the host


async def test_egress_allowed_when_opted_in() -> None:
    fake = FakeProvider([_GOOD], is_local=False)
    out = await advise("doc", provider=fake, cfg=_cfg(allow_remote=True))
    assert isinstance(out, LlmAdvisory)
    assert len(fake.calls) == 1


async def test_corrective_prompt_never_echoes_model_output() -> None:
    fake = FakeProvider(["TOTALLY NOT JSON sentinel_xyz", _GOOD])
    out = await advise("doc", provider=fake, cfg=_cfg())
    assert isinstance(out, LlmAdvisory)
    # The second call's appended corrective message must not amplify injection.
    corrective = fake.calls[1][-1]
    assert corrective.role == "user"
    assert "sentinel_xyz" not in corrective.content


async def test_defaults_to_factory_and_config(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider([_GOOD])
    monkeypatch.setattr(advise_mod, "get_provider", lambda **_: fake)
    # No provider, no cfg → load_llm_config() + get_provider() are exercised.
    out = await advise("doc")
    assert isinstance(out, LlmAdvisory)
    assert len(fake.calls) == 1
