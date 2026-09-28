# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calibration application is pure and CI-testable without the (gitignored) model."""

from __future__ import annotations

import pytest

from eyenet.incidents.classifier import (
    apply_calibration,
    enrich_text,
    model_dir,
    prefilter_labels,
)

pytestmark = pytest.mark.unit

_LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]


def test_enrich_text_no_attachment_is_identity() -> None:
    assert enrich_text("selling rdp access", None) == "selling rdp access"
    assert enrich_text("selling rdp access", []) == "selling rdp access"
    assert enrich_text("body", [""]) == "body"  # blank filenames dropped


def test_enrich_text_appends_attachment_marker() -> None:
    out = enrich_text("Pass: @x", ["HESOYAM CLOUD.rar"])
    assert out.startswith("Pass: @x")
    assert "HESOYAM CLOUD.rar" in out
    assert out != "Pass: @x"  # marker actually added


def test_enrich_text_is_deterministic_and_joins_multiple() -> None:
    # train/serve MUST produce identical bytes for the same input
    a = enrich_text("b", ["a.zip", "c.rar"])
    assert a == enrich_text("b", ["a.zip", "c.rar"])
    assert "a.zip" in a and "c.rar" in a


def test_apply_calibration_fires_above_threshold() -> None:
    # a=1,b=0,thr=0.5 -> fires when logit>0. Only 'tooling' has a positive logit here.
    calib = {k: {"a": 1.0, "b": 0.0, "thr": 0.5} for k in _LABELS}
    logits = [-5.0, -5.0, -5.0, -5.0, -5.0, 3.0]
    scores = {s.label: s for s in apply_calibration(logits, _LABELS, calib)}
    assert scores["tooling"].fired
    assert scores["tooling"].prob > 0.9
    assert not scores["incident"].fired
    assert scores["incident"].prob < 0.1


def test_calibration_shifts_boundary() -> None:
    # A compressed logit (-2) sits below 0.5 raw, but a>1/b>0 can lift it past thr.
    raw = apply_calibration(
        [-2.0] + [-9] * 5, _LABELS, {k: {"a": 1.0, "b": 0.0, "thr": 0.5} for k in _LABELS}
    )
    assert not raw[0].fired  # sigmoid(-2) ~ 0.12 < 0.5
    cal = apply_calibration(
        [-2.0] + [-9] * 5, _LABELS, {"incident": {"a": 1.0, "b": 3.0, "thr": 0.5}}
    )
    assert cal[0].fired  # sigmoid(-2+3)=sigmoid(1) ~ 0.73 >= 0.5


def test_unknown_head_defaults_to_identity() -> None:
    # missing calib entry -> a=1,b=0,thr=0.5 (no crash, sane default)
    scores = apply_calibration([4.0] + [-9] * 5, _LABELS, {})
    assert scores[0].fired


def test_prefilter_fusion_catches_structural_infostealer() -> None:
    # The model-only classifier missed this (scored under threshold); the prefilter's
    # cloud_pass signal catches it via fusion. Pure, no model needed.
    assert "stealer_logs" in prefilter_labels("fresh cloud logs daily, pass: t.me/logschan")


def test_prefilter_fusion_quiet_on_benign() -> None:
    assert prefilter_labels("gm everyone hows the market today") == set()


@pytest.mark.skipif(
    not (model_dir() / "calibration.json").exists(), reason="no local trained model"
)
def test_classify_end_to_end_when_model_present() -> None:
    from eyenet.incidents.classifier import fired_labels

    labels = fired_labels("selling my private FUD crypter, fully undetectable, DM for price")
    assert "tooling" in labels
