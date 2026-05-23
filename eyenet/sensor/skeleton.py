"""`SensorSkeleton` — subscribes to `raw.message.>` as queue group `sensor`.

M1: logs receipt, runs no primitives. M2 plugs in BEHAVE-TEXT primitives.
"""

from __future__ import annotations

from collections.abc import Iterable

from behave_text.spec import ValueTypeSpec

from eyenet.contracts.observation import ObservationEnvelope
from eyenet.contracts.raw_message import RawMessageEnvelope
from eyenet.contracts.sensor import SensorBase
from eyenet.service import ServiceBase


class SensorSkeleton(ServiceBase, SensorBase):
    @property
    def name(self) -> str:
        return "sensor"

    @property
    def instance_id(self) -> str:
        return "sensor_default"

    def primitives(self) -> Iterable[tuple[str, ValueTypeSpec]]:
        return []

    async def on_subscribe(self) -> None:
        async def _on_raw(_subject: str, payload: bytes, _headers: dict[str, str]) -> None:
            env = RawMessageEnvelope.model_validate_json(payload)
            self._log.info(
                "sensor.raw_received",
                evidence_ref=env.evidence_ref,
                actor_key=env.actor_key,
            )

        await self._bus.subscribe("raw.message.>", _on_raw, queue_group="sensor")

    async def on_raw_message(
        self,
        envelope: RawMessageEnvelope,  # noqa: ARG002 — M1 stub; real impl uses it in M2
    ) -> Iterable[ObservationEnvelope]:
        return []


__all__ = ["SensorSkeleton"]
