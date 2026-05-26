"""SourceTable — see contracts/source.py."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from eyenet.contracts.enums import SourceKind

from ._base import new_uuid7


class SourceTable(SQLModel, table=True):
    """Platform-origin row (MODELS §1.1).

    ``canonical_url`` is display-only — operator-set, validated against the
    Source's primary :class:`SourceDomainTable` row before write. Collectors
    no longer set it on Source creation: a freshly-created Source has
    ``canonical_url=None`` until the operator (via M9.D1 PATCH) binds it to
    a primary SourceDomain. See ``set_source_canonical_url`` on the storage
    layer for the validation contract.
    """

    __tablename__ = "source"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    kind: SourceKind = Field(index=True)
    display_name: str
    canonical_url: str | None = None
    created_at: datetime
    notes: str | None = None


__all__ = ["SourceTable"]
