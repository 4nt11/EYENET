"""CLI runtime config — env vars + flag parsing."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class LinkerThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # UNCALIBRATED defaults. Override per operator via config.toml.
    function_word_simhash_hamming: int = Field(default=8, ge=0, le=64)
    char_ngram_simhash_hamming: int = Field(default=10, ge=0, le=64)

    def for_comparator(self, name: str) -> int:
        """Return the configured threshold for a comparator by name."""
        return getattr(self, name, 8)


class LinkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: LinkerThresholds = Field(default_factory=LinkerThresholds)


class RuntimeConfig(BaseModel):
    """Resolved runtime config for an EYENET service process."""

    model_config = ConfigDict(extra="forbid")

    nats_url: str = Field(default="nats://127.0.0.1:4222")
    data_dir: Path
    identities_path: Path | None = None
    otlp_endpoint: str | None = None
    use_memory_bus: bool = False  # tests / dev-loop convenience
    linker: LinkerConfig = Field(default_factory=LinkerConfig)

    @classmethod
    def from_env(
        cls,
        *,
        data_dir: Path | None = None,
        identities_path: Path | None = None,
        nats_url: str | None = None,
        use_memory_bus: bool | None = None,
    ) -> RuntimeConfig:
        return cls(
            nats_url=nats_url or os.environ.get("EYENET_NATS_URL", "nats://127.0.0.1:4222"),
            data_dir=data_dir or Path(os.environ.get("EYENET_DATA_DIR", "./data")),
            identities_path=identities_path or _opt_path(os.environ.get("EYENET_IDENTITIES")),
            otlp_endpoint=os.environ.get("EYENET_OTLP_ENDPOINT") or None,
            use_memory_bus=use_memory_bus
            if use_memory_bus is not None
            else os.environ.get("EYENET_MEMORY_BUS", "0") == "1",
        )


def _opt_path(s: str | None) -> Path | None:
    return Path(s) if s else None


__all__ = ["LinkerConfig", "LinkerThresholds", "RuntimeConfig"]
