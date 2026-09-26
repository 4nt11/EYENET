"""Incident multi-label classifier: the fine-tuned mmBERT encoder + per-head Platt
calibration, scoring a message into the taxonomy labels (development/incident-taxonomy.md).

The model directory (``EYENET_INCIDENT_MODEL_DIR``, default ``dataset/mmbert-incident-ml``)
must contain the HF model plus ``labels.json`` (head order) and ``calibration.json``
({label: {a, b, thr}}). A head fires when ``sigmoid(a*logit + b) >= thr``.

Heavy deps (torch/transformers) are imported lazily inside ``_load`` so that importing
this module — e.g. for :func:`apply_calibration` — stays cheap and torch-free.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path("dataset/mmbert-incident-ml")

# Canonical prefilter-signal -> taxonomy-label map (development/incident-taxonomy.md).
# The single source of truth: the classifier's prefilter fusion AND the silver
# bootstrap (dataset/bootstrap_silver.py) both import this. Deterministic/structural
# categories the model tends to under-recall (stealer clouds, dump hosts, webshells,
# tool sales) are caught here regardless of the model's score.
SIG2LABEL: dict[str, str] = {
    "deface_banner": "incident", "ddos_command": "incident", "check_host": "incident",
    "compromise_confirmed": "incident", "multi_target": "incident",
    "leak_host": "leak", "leak_label": "leak", "target_dump_file": "leak",
    "pii_schema": "leak", "hash_list": "leak", "cred_combo": "leak",
    "cred_label": "leak", "onion_url": "leak",
    "stealer_logs": "infostealer", "cloud_pass": "infostealer",
    "access_material": "access_sale",
    "tool_sale": "tooling",
}


def model_dir() -> Path:
    return Path(os.environ.get("EYENET_INCIDENT_MODEL_DIR", str(_DEFAULT_DIR)))


@dataclass(frozen=True)
class HeadScore:
    """One taxonomy head's calibrated probability and fire decision for a message."""

    label: str
    prob: float
    fired: bool


def _sigmoid(x: float) -> float:
    # stable enough for single scores; avoids overflow on large-negative logits
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def apply_calibration(
    logits: list[float], labels: list[str], calib: dict[str, dict[str, float]]
) -> list[HeadScore]:
    """Pure: raw per-head logits -> calibrated HeadScores. No model, no torch."""
    out: list[HeadScore] = []
    for i, k in enumerate(labels):
        c = calib.get(k, {"a": 1.0, "b": 0.0, "thr": 0.5})
        p = _sigmoid(c["a"] * logits[i] + c["b"])
        out.append(HeadScore(label=k, prob=round(p, 4), fired=p >= c["thr"]))
    return out


@lru_cache(maxsize=1)
def _load() -> tuple[list[str], dict[str, Any], Any, Any, Any]:
    import torch  # noqa: PLC0415  (lazy — keep module import torch-free)
    from transformers import (  # noqa: PLC0415
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    d = model_dir()
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    calib = json.loads((d / "calibration.json").read_text(encoding="utf-8"))
    tok = AutoTokenizer.from_pretrained(str(d))
    model = AutoModelForSequenceClassification.from_pretrained(str(d)).eval()
    return labels, calib, tok, model, torch


def classify(text: str) -> list[HeadScore]:
    """Score one message into calibrated per-head decisions (model loads once, cached)."""
    labels, calib, tok, model, torch = _load()
    x = tok(text, return_tensors="pt", truncation=True, max_length=128)
    with torch.no_grad():
        logits = model(**x).logits[0].tolist()
    return apply_calibration(logits, labels, calib)


def prefilter_labels(text: str) -> set[str]:
    """Deterministic labels from the structural prefilter (no model, no torch)."""
    from .prefilter import scan  # noqa: PLC0415  (cheap, pure RE2)

    return {SIG2LABEL[s] for s in scan(text).signals if s in SIG2LABEL}


def fired_labels(text: str) -> list[str]:
    """The cascade: labels fired by the calibrated model OR the structural prefilter,
    in taxonomy head order. The prefilter catches structural cases (stealer clouds,
    dump hosts, webshells, tool sales) the model under-recalls; the model catches the
    semantic cases the prefilter cannot express."""
    scores = classify(text)
    fired = {s.label for s in scores if s.fired} | prefilter_labels(text)
    return [s.label for s in scores if s.label in fired]  # head order
