"""PLAN §4.1 — we import BEHAVE-TEXT's Observation; we do NOT redefine it."""

from __future__ import annotations

import pytest


@pytest.mark.contract
def test_observation_is_reexport() -> None:
    from behave_text.spec import Observation as Upstream

    from eyenet.contracts.observation import ObservationEnvelope

    assert ObservationEnvelope is Upstream


@pytest.mark.contract
def test_topic_prefix_matches_plan_taxonomy() -> None:
    from eyenet.contracts.observation import TOPIC_PREFIX

    assert TOPIC_PREFIX == "actor.observation.text"
