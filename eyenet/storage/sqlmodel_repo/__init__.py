# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLModelRepository — generic SQLModel/SQLAlchemy implementation of BaseRepository.

Composed of one mixin per domain. Subclasses (e.g. SQLiteRepository)
override only the dialect-specific bits — the async audit `BEGIN
IMMEDIATE` lock, pragma wiring, and engine construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eyenet.storage.repository import BaseRepository

from .actors import ActorsMixin
from .attachments import AttachmentsMixin
from .audit import AuditMixin
from .cases import CasesMixin
from .clearance import ClearanceMixin
from .corpus import CorpusMixin
from .cursors import CursorsMixin
from .feedback import FeedbackMixin
from .graph import GraphMixin
from .linkages import LinkagesMixin
from .messages import MessagesMixin
from .observations import ObservationsMixin
from .personas import PersonasMixin
from .profiles import ProfilesMixin
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
    CorpusMixin,
    CursorsMixin,
    FeedbackMixin,
    GraphMixin,
    LinkagesMixin,
    MessagesMixin,
    ObservationsMixin,
    PersonasMixin,
    ProfilesMixin,
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

    async def close(self) -> None:
        await self.engine.dispose()
        await self.audit_engine.dispose()


__all__ = ["SQLModelRepository"]
