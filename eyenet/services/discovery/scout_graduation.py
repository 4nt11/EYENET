# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scout graduation pipeline (API_PLAN §4.12.5, M9.E4).

A scout identity joins a freshly-approved candidate group and is observed for an
``observation_window_days`` window (default 7). On a clean window it graduates to
``monitor``; if it is burned (ban / anti-spam / FloodWait storm — signals the
collector raises in E5) it is quarantined and its candidate parked.

This service owns the **happy path** on a periodic tick: graduate every scout
whose collector has held a still-active membership past the window.
:meth:`quarantine_scout` is the **burn path**, invoked by the runtime when a ban
is detected; the live ban-detection trigger is wired by the Telegram collector
in E5, but the transition logic + audit live here and are tested directly.

The window is a service-level default; a per-source override
(``Source.scout_observation_window_days``) lands with the other deferred
``Source.default_*`` discovery fields.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from eyenet.contracts.audit_subjects import AuditSubject
from eyenet.contracts.enums import CandidateState
from eyenet.service import ServiceBase
from eyenet.telemetry.logging import get_logger

if TYPE_CHECKING:
    from uuid import UUID

    from eyenet.contracts.bus import Bus
    from eyenet.storage.repository import BaseRepository

_log = get_logger()
_DEFAULT_WINDOW_DAYS = 7


class ScoutGraduationService(ServiceBase):
    """Hourly graduation of clean scouts + the burn/quarantine path (M9.E4)."""

    def __init__(
        self,
        *,
        bus: Bus,
        storage: BaseRepository,
        observation_window_days: int = _DEFAULT_WINDOW_DAYS,
    ) -> None:
        super().__init__(bus=bus, storage=storage)
        self._window = timedelta(days=observation_window_days)

    @property
    def name(self) -> str:
        return "scout_graduation"

    @property
    def instance_id(self) -> str:
        return "scout_graduation_default"

    async def on_subscribe(self) -> None:
        """Tick-driven; no bus subscription (run with an hourly tick interval)."""

    async def tick(self) -> None:
        await self.graduate_due(datetime.now(tz=UTC))

    async def graduate_due(self, now: datetime) -> int:
        """Graduate every scout whose observation window has elapsed cleanly.

        Returns the number graduated.
        """
        joined_before = now - self._window
        identity_ids = await self._storage.list_graduating_scouts(joined_before)
        for identity_id in identity_ids:
            await self._storage.graduate_identity(identity_id=identity_id, now=now)
            await self.audit.emit(
                event=AuditSubject.IDENTITY_GRADUATED.value,
                subject_kind="identity",
                subject_id=identity_id,
                payload={"graduated_at": now.isoformat(), "from_role": "scout"},
            )
            _log.info("scout_graduation.graduated", identity_id=str(identity_id))
        return len(identity_ids)

    async def quarantine_scout(
        self,
        *,
        identity_id: UUID,
        reason: str,
        candidate_id: UUID | None = None,
    ) -> None:
        """Burn a scout (→ BURNED/QUARANTINE) and park its candidate (§4.12.5).

        Invoked by the runtime on a detected ban/flag. The candidate transition
        is best-effort: it is only parked if it is in a state that legally
        allows it (``joined → parked``)."""
        await self._storage.burn_identity(identity_id=identity_id)
        if candidate_id is not None:
            candidate = await self._storage.get_candidate(candidate_id)
            if candidate is not None and candidate.state is CandidateState.JOINED:
                await self._storage.transition_candidate(
                    candidate_id=candidate_id,
                    to_state=CandidateState.PARKED,
                    rejection_reason=reason,
                )
        await self.audit.emit(
            event=AuditSubject.IDENTITY_BURNED.value,
            subject_kind="identity",
            subject_id=identity_id,
            payload={
                "reason": reason,
                "candidate_id": str(candidate_id) if candidate_id is not None else None,
            },
        )
        _log.warning("scout_graduation.burned", identity_id=str(identity_id), reason=reason)


__all__ = ["ScoutGraduationService"]
