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
    "deface_banner": "incident",
    "ddos_command": "incident",
    "check_host": "incident",
    "compromise_confirmed": "incident",
    "multi_target": "incident",
    "leak_host": "leak",
    "leak_label": "leak",
    "target_dump_file": "leak",
    "pii_schema": "leak",
    "hash_list": "leak",
    "cred_combo": "leak",
    "cred_label": "leak",
    "onion_url": "leak",
    "stealer_logs": "infostealer",
    "cloud_pass": "infostealer",  # nosec B105 — signal name, not a password
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
    # The model dir is fully self-contained (weights + tokenizer + config), so nothing
    # is ever fetched. Force offline anyway so transformers/HF cannot phone home for
    # version/etag checks — guarantees a network-free load (operator posture). setdefault
    # lets an operator opt back into online if they ever need to.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch  # noqa: PLC0415  (lazy — keep module import torch-free)
    from transformers import (  # noqa: PLC0415
        AutoModelForSequenceClassification,
        AutoTokenizer,
    )

    d = model_dir()
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    calib = json.loads((d / "calibration.json").read_text(encoding="utf-8"))
    # nosec B615 — loads from a LOCAL, operator-provided dir (str(d)) with HF offline
    # forced above: no Hub download happens, so revision pinning is not applicable.
    tok = AutoTokenizer.from_pretrained(str(d))  # nosec B615
    model = AutoModelForSequenceClassification.from_pretrained(str(d)).eval()  # nosec B615
    # Device: EYENET_INCIDENT_DEVICE overrides (set "cpu" to keep the GPU free for the
    # stage-3 LLM); otherwise CUDA when available, else CPU.
    device = os.environ.get("EYENET_INCIDENT_DEVICE") or (
        "cuda" if torch.cuda.is_available() else "cpu"
    )
    model = model.to(device)
    return labels, calib, tok, model, torch


_INFER_BATCH = 64  # GPU sub-batch; sweep_ml ran bs=64 comfortably in 8GB


def classify_batch(texts: list[str]) -> list[list[HeadScore]]:
    """Score many messages in padded forward passes (one per <=64 chunk). Returns one
    list[HeadScore] per input text, in input order. The throughput path for the service."""
    if not texts:
        return []
    labels, calib, tok, model, torch = _load()
    out: list[list[HeadScore]] = []
    for i in range(0, len(texts), _INFER_BATCH):
        chunk = texts[i : i + _INFER_BATCH]
        x = tok(chunk, return_tensors="pt", truncation=True, max_length=128, padding=True)
        x = x.to(model.device)
        with torch.no_grad():
            logits = model(**x).logits.tolist()
        out.extend(apply_calibration(row, labels, calib) for row in logits)
    return out


def classify(text: str) -> list[HeadScore]:
    """Score one message into calibrated per-head decisions (model loads once, cached)."""
    return classify_batch([text])[0]


def fired_labels_batch(texts: list[str]) -> list[list[str]]:
    """Batch cascade: per message, model-fired union prefilter labels, in head order.
    One padded forward pass per chunk; the prefilter runs per message (pure RE2, cheap)."""
    scored = classify_batch(texts)
    result: list[list[str]] = []
    for text, scores in zip(texts, scored, strict=True):
        fired = {s.label for s in scores if s.fired} | prefilter_labels(text)
        result.append([s.label for s in scores if s.label in fired])
    return result


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
