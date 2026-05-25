"""Schema-level tests for sensitivity columns on Observation + Attachment (§4.9).

Storage-layer CHECK enforces monotone-up only: operator_tier_override (if set)
must rank >= classifier_tier. This is the LAST line of defence — endpoint
guards (§4.9) and audit trail (§4.9) are the first two; the CHECK refuses
even a hand-crafted SQLite INSERT that bypasses those.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from eyenet.contracts.enums import (
    AttachmentKind,
    SensitivityTier,
    ValueKind,
)
from eyenet.models.message import AttachmentTable, MessageTable
from eyenet.models.observation import ObservationTable
from eyenet.storage.factory import get_repository
from eyenet.storage.repository import BaseRepository  # noqa: F401

_NOW = datetime(2026, 5, 24, tzinfo=UTC)


@pytest.fixture
def obs_session() -> Session:
    import os
    os.environ.setdefault("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)


@pytest.fixture
def msg_session() -> Session:
    """Sessions for AttachmentTable need MessageTable's FK target available."""
    import os
    os.environ.setdefault("EYENET_STORAGE_TYPE", "sqlite")
    storage = get_repository(in_memory=True)
    return Session(storage.sync_engine)


def _obs(**overrides: object) -> ObservationTable:
    defaults: dict[str, object] = {
        "actor_id": uuid4(),
        "primitive_namespace": "test",
        "primitive_name": "test.primitive",
        "primitive_version": "0.1",
        "value_kind": ValueKind.NUMERIC,
        "value_numeric": 0.5,
        "observed_at": _NOW,
        "sensor_instance": "t",
    }
    defaults.update(overrides)
    return ObservationTable(**defaults)  # type: ignore[arg-type]


# --- Observation -----------------------------------------------------------


@pytest.mark.unit
def test_observation_default_classifier_is_normal(obs_session: Session) -> None:
    o = _obs()
    obs_session.add(o)
    obs_session.commit()
    obs_session.refresh(o)
    assert o.classifier_tier is SensitivityTier.NORMAL
    assert o.operator_tier_override is None


@pytest.mark.unit
def test_observation_override_none_always_accepted(obs_session: Session) -> None:
    obs_session.add(_obs(classifier_tier=SensitivityTier.CLASSIFIED))
    obs_session.commit()


@pytest.mark.unit
def test_observation_promote_normal_to_classified_accepted(obs_session: Session) -> None:
    obs_session.add(
        _obs(
            classifier_tier=SensitivityTier.NORMAL,
            operator_tier_override=SensitivityTier.CLASSIFIED,
        )
    )
    obs_session.commit()


@pytest.mark.unit
def test_observation_demote_classified_to_normal_rejected(obs_session: Session) -> None:
    obs_session.add(
        _obs(
            classifier_tier=SensitivityTier.CLASSIFIED,
            operator_tier_override=SensitivityTier.NORMAL,
        )
    )
    with pytest.raises(IntegrityError):
        obs_session.commit()


@pytest.mark.unit
def test_observation_demote_restricted_to_normal_rejected(obs_session: Session) -> None:
    obs_session.add(
        _obs(
            classifier_tier=SensitivityTier.RESTRICTED,
            operator_tier_override=SensitivityTier.NORMAL,
        )
    )
    with pytest.raises(IntegrityError):
        obs_session.commit()


@pytest.mark.unit
def test_observation_demote_classified_to_restricted_rejected(obs_session: Session) -> None:
    obs_session.add(
        _obs(
            classifier_tier=SensitivityTier.CLASSIFIED,
            operator_tier_override=SensitivityTier.RESTRICTED,
        )
    )
    with pytest.raises(IntegrityError):
        obs_session.commit()


@pytest.mark.unit
def test_observation_same_tier_accepted(obs_session: Session) -> None:
    obs_session.add(
        _obs(
            classifier_tier=SensitivityTier.RESTRICTED,
            operator_tier_override=SensitivityTier.RESTRICTED,
        )
    )
    obs_session.commit()


# --- Attachment ------------------------------------------------------------


def _attachment(message_id: UUID, **overrides: object) -> AttachmentTable:
    defaults: dict[str, object] = {
        "message_id": message_id,
        "kind": AttachmentKind.DOCUMENT,
        "mime": "application/pdf",
        "size_bytes": 1024,
        "sha256": "0" * 64,
    }
    defaults.update(overrides)
    return AttachmentTable(**defaults)  # type: ignore[arg-type]


def _seed_message(session: Session) -> UUID:
    """Insert a message via raw SQL — FK targets in `messages.db` aren't all
    available in this isolated test (group/source/actor live there too)."""
    # The in-memory engine has FK=OFF (per engines.py:84), so we can insert
    # an Attachment with a synthetic message_id and exercise just the
    # sensitivity CHECK.
    return uuid4()


@pytest.mark.unit
def test_attachment_promote_accepted(msg_session: Session) -> None:
    msg_session.add(
        _attachment(
            _seed_message(msg_session),
            classifier_tier=SensitivityTier.NORMAL,
            operator_tier_override=SensitivityTier.CLASSIFIED,
        )
    )
    msg_session.commit()


@pytest.mark.unit
def test_attachment_demote_rejected(msg_session: Session) -> None:
    msg_session.add(
        _attachment(
            _seed_message(msg_session),
            classifier_tier=SensitivityTier.CLASSIFIED,
            operator_tier_override=SensitivityTier.NORMAL,
        )
    )
    with pytest.raises(IntegrityError):
        msg_session.commit()


@pytest.mark.unit
@pytest.mark.parametrize("tier", list(SensitivityTier))
def test_attachment_every_tier_round_trips(msg_session: Session, tier: SensitivityTier) -> None:
    a = _attachment(_seed_message(msg_session), classifier_tier=tier)
    msg_session.add(a)
    msg_session.commit()
    msg_session.refresh(a)
    assert a.classifier_tier is tier


# Silence unused-import warning — MessageTable is referenced for FK metadata
_ = MessageTable
