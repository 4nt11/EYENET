"""LinkageVerifierResultTable — the M8 Verifier's settled result per linkage.

The Verifier scores every PROPOSED pair (NCD + General Impostors), takes the
mean as a composite, and promotes to SUSPECTED when it clears the floor. Until
now that composite + per-verifier scores survived only as a `notes` string and
an audit payload — not queryable. This table persists the structured result so
the actor dossier can surface it per neighbor.

Recorded on EVERY scored linkage (promoted or below-floor), for evidence.
Colocated with `linkage` in the PROFILES store so the FK resolves natively.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column
from sqlalchemy import JSON as SA_JSON
from sqlmodel import Field, SQLModel

from ._base import new_uuid7


class LinkageVerifierResultTable(SQLModel, table=True):
    __tablename__ = "linkage_verifier_result"

    id: UUID = Field(default_factory=new_uuid7, primary_key=True)
    linkage_id: UUID = Field(foreign_key="linkage.id", index=True, unique=True)
    composite: float
    floor: float
    # "suspected" when composite >= floor (promoted), else "below_floor".
    state: str
    # Per-verifier rows: [{method, score, confidence, skipped, detail}, ...].
    results: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(SA_JSON))
    computed_at: datetime


__all__ = ["LinkageVerifierResultTable"]
