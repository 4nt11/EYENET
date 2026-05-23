"""`SensorBase` ABC — stateless workers running BEHAVE-TEXT primitives (PLAN §2.2).

Sensors subscribe to `raw.message.>` as a NATS queue group. They MUST be
stateless: per-actor state is the Engine's job. A sensor instance is allowed
to keep in-process caches of corpus windows it has already pulled, but those
caches must be reconstructible from the corpus store + cursor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from behave_text.spec import ValueTypeSpec

from .observation import ObservationEnvelope
from .raw_message import RawMessageEnvelope


class SensorBase(ABC):
    """Stateless sensor."""

    @abstractmethod
    def primitives(self) -> Iterable[tuple[str, ValueTypeSpec]]:
        """Return `[(primitive_name, ValueTypeSpec)]` this sensor computes.

        The names MUST be present in BEHAVE-TEXT's PRIMITIVE_REGISTRY; a
        sensor that emits an unknown primitive would fail Observation
        validation (`behave_text.spec.envelope.Observation`).
        """

    @abstractmethod
    async def on_raw_message(
        self,
        envelope: RawMessageEnvelope,
    ) -> Iterable[ObservationEnvelope]:
        """Compute zero-or-more Observations from a single raw message.

        Per PLAN §8.4, a failed primitive MUST NOT abort sibling primitives.
        Concrete sensors handle that internally and surface failures via
        spans/logs.
        """


__all__ = ["SensorBase"]
