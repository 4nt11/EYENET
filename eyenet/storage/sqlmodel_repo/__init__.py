# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLModelRepository — generic SQLModel/SQLAlchemy implementation of BaseRepository.

Composed of one mixin per domain. Subclasses (e.g. SQLiteRepository)
override only the dialect-specific bits — the async audit `BEGIN
IMMEDIATE` lock, pragma wiring, and engine construction.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from eyenet.storage.repository import BaseRepository

from ._helpers import safe_session
from .actors import ActorsMixin
from .attachments import AttachmentsMixin
from .audit import AuditMixin
from .cases import CasesMixin
from .clearance import ClearanceMixin
from .collectors import CollectorsMixin
from .corpus import CorpusMixin
from .cursors import CursorsMixin
from .feedback import FeedbackMixin
from .graph import GraphMixin
from .linkages import LinkagesMixin
from .messages import MessagesMixin
from .observations import ObservationsMixin
from .personas import PersonasMixin
from .profiles import ProfilesMixin
from .sources import SourcesMixin
from .syslog import SyslogMixin
from .vectors import VectorsMixin

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession


class SQLModelRepository(
    ActorsMixin,
    AttachmentsMixin,
    AuditMixin,
    CasesMixin,
    ClearanceMixin,
    CollectorsMixin,
    CorpusMixin,
    CursorsMixin,
    FeedbackMixin,
    GraphMixin,
    LinkagesMixin,
    MessagesMixin,
    ObservationsMixin,
    PersonasMixin,
    ProfilesMixin,
    SourcesMixin,
    SyslogMixin,
    VectorsMixin,
    BaseRepository,
):
    """Generic SQLModel/SQLAlchemy repo. Subclasses set engines + factories."""

    engine: AsyncEngine
    sync_engine: Engine
    audit_engine: AsyncEngine
    audit_sync_engine: Engine
    _session_factory: async_sessionmaker[AsyncSession]
    _audit_session_factory: async_sessionmaker[AsyncSession]

    async def _append_audit_locked(self, row_data: dict[str, Any]) -> Any:
        """Dialect-specific atomic audit append. SQLite uses BEGIN IMMEDIATE."""
        raise NotImplementedError("subclass must override _append_audit_locked")

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Escape hatch: open an AsyncSession on the main engine.

        For domain operations, prefer the typed flat methods. This is
        for collector-side custom transactions (Matrix edit patching,
        reaction insertion) that can't be expressed as a single repo call.
        """
        async with safe_session(self._session_factory) as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
        await self.audit_engine.dispose()


__all__ = ["SQLModelRepository"]
