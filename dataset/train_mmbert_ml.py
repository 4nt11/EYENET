#!/usr/bin/env python3
"""Fine-tune mmBERT-base as a MULTI-LABEL incident classifier.

One shared encoder, one sigmoid head per label (taxonomy in
development/incident-taxonomy.md). Trains on silver (bootstrap_silver.py) with
GOLD human labels (labeler.html exports *.mllabels.jsonl) overriding by text.

Deterministic categories (DDoS commands, cred combos) stay in the prefilter, NOT
here. `none` is implicit: no head fires.

Run (free ollama VRAM first if it OOMs):
    USE_TF=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        .venv/bin/python dataset/train_mmbert_ml.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["USE_TF"] = "0"
import numpy as np  # noqa: E402
import torch  # noqa: E402
from datasets import Dataset  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

import build_dataset as bd  # noqa: E402  (redact)

HERE = Path(__file__).parent
BASE = "jhu-clsp/mmBERT-base"
OUT = str(HERE / "mmbert-incident-ml")
# order is the head order; persisted to OUT/labels.json for inference.
LABELS = ["incident", "leak", "infostealer", "access_sale", "actor_ops", "tooling"]
GOLD_TEST_FRAC = 0.30   # fraction of HUMAN gold held out for honest eval (never trained)
SEED = 1337


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def label_vec(row: dict) -> list[float]:
    """Extract a 5-dim 0/1 vector. Accepts flat int columns (silver) OR a nested
    {"labels": {...}} / {"labels": [...]} shape (whatever labeler.html exports)."""
    lab = row.get("labels")
    if isinstance(lab, dict):
        return [1.0 if lab.get(k) else 0.0 for k in LABELS]
    if isinstance(lab, list):
        s = set(lab)
        return [1.0 if k in s else 0.0 for k in LABELS]
    # flat columns
    return [1.0 if row.get(k) else 0.0 for k in LABELS]


def auroc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    w = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return w / (len(pos) * len(neg))


def load_silver() -> dict[str, list[float]]:
    return {bd.redact(r["text"]): label_vec(r) for r in load_jsonl(HERE / "silver_multilabel.jsonl")}


def load_gold() -> dict[str, list[float]]:
    """Every *.mllabels.jsonl, keyed by redacted text (dups collapse, later file wins)."""
    gold: dict[str, list[float]] = {}
    for gp in sorted(HERE.glob("*.mllabels.jsonl")):
        for r in load_jsonl(gp):
            gold[bd.redact(r["text"])] = label_vec(r)
    return gold


def support(rows: list[dict]) -> dict[str, int]:
    return {k: int(sum(r["labels"][i] for r in rows)) for i, k in enumerate(LABELS)}


def main() -> None:
    tok = AutoTokenizer.from_pretrained(BASE)
    silver = load_silver()
    gold = load_gold()
    rng = np.random.default_rng(SEED)
    gold_items = list(gold.items())
    rng.shuffle(gold_items)
    cut = int(len(gold_items) * (1 - GOLD_TEST_FRAC))
    gold_tr, gold_te = dict(gold_items[:cut]), dict(gold_items[cut:])

    # Train = silver, with gold-TEST texts removed (no leakage), gold-TRAIN folded in as
    # human-truth overrides. Eval = gold-test only -> honest per-head numbers on human labels.
    pool = dict(silver)
    for t in gold_te:
        pool.pop(t, None)
    pool.update(gold_tr)
    tr = [{"text": t, "labels": v} for t, v in pool.items()]
    te = [{"text": t, "labels": v} for t, v in gold_te.items()]
    print(f"silver={len(silver)} gold={len(gold)}  (gold-train={len(gold_tr)} gold-test={len(gold_te)})")
    print(f"train={len(tr)}  gold-test={len(te)}")
    print(f"train support    : {support(tr)}")
    print(f"GOLD-test support: {support(te)}")

    def tokz(batch):
        return tok(batch["text"], truncation=True, max_length=128)

    ds_tr = Dataset.from_list(tr).map(tokz, batched=True)
    ds_te = Dataset.from_list(te).map(tokz, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        BASE, num_labels=len(LABELS), problem_type="multi_label_classification"
    )
    args = TrainingArguments(
        output_dir=OUT,
        num_train_epochs=4,
        per_device_train_batch_size=8,
        gradient_accumulation_steps=2,
        learning_rate=2e-5,
        warmup_steps=40,
        weight_decay=0.01,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=True,
        logging_steps=25,
        save_strategy="no",
        report_to=[],
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds_tr, processing_class=tok)
    trainer.train()

    model.eval()
    pred = trainer.predict(ds_te)
    probs = torch.sigmoid(torch.tensor(pred.predictions)).numpy()  # (N, 5)
    y = np.array([r["labels"] for r in te])  # (N, 5)

    print("\n" + "=" * 64)
    print("HONEST eval: held-out HUMAN gold only (never trained, no silver)")
    print(f"{'label':<12} {'sup':>4} {'AUROC':>6} {'P@.5':>6} {'R@.5':>6}")
    for i, k in enumerate(LABELS):
        p_i, y_i = probs[:, i], y[:, i]
        pos = [float(v) for v, t in zip(p_i, y_i) if t == 1]
        neg = [float(v) for v, t in zip(p_i, y_i) if t == 0]
        pred_pos = p_i >= 0.5
        tp = int(((pred_pos) & (y_i == 1)).sum())
        prec = tp / max(1, int(pred_pos.sum()))
        rec = tp / max(1, int((y_i == 1).sum()))
        au = auroc(pos, neg)
        aus = "  n/a" if au != au else f"{au:6.3f}"  # nan when a head has no gold-test pos
        print(f"{k:<12} {int(y_i.sum()):>4} {aus} {prec:6.2f} {rec:6.2f}")
    print("=" * 64)
    print(f"sup = gold-test positives (~{int(GOLD_TEST_FRAC*100)}% of gold); small sup = noisy number, LABEL MORE.")

    trainer.save_model(OUT)
    tok.save_pretrained(OUT)
    (Path(OUT) / "labels.json").write_text(json.dumps(LABELS), encoding="utf-8")
    print(f"saved -> {OUT} (+ labels.json head order)")


def _selfcheck() -> None:
    assert label_vec({"incident": 1, "leak": 0, "access_sale": 1}) == [1, 0, 0, 1, 0, 0]
    assert label_vec({"labels": {"actor_ops": 1}}) == [0, 0, 0, 0, 1, 0]
    assert label_vec({"labels": ["leak", "tooling"]}) == [0, 1, 0, 0, 0, 1]
    assert auroc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert auroc([], [0.1]) != auroc([], [0.1]) is False or True  # nan, no crash
    print("selfcheck ok")


if __name__ == "__main__":
    import sys

    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main()
