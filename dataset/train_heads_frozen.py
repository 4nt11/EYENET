#!/usr/bin/env python3
"""PoC: frozen-encoder, head-only fine-tune (fold operator corrections in, safely).

The full retrain (train_mmbert_ml.py) updates the whole encoder. When you only want to
absorb a trickle of operator corrections (incidents-export-labels -> *.mllabels.jsonl),
retraining the encoder on a handful of rows risks catastrophic forgetting AND is slow.

This starts from the ALREADY-deployed model, FREEZES the encoder (preserving mmBERT's
multilingual embeddings), and trains only the classifier head on silver + gold. It is the
lazy-correct "incremental" step: cheap (the head is tiny -> minutes on a 5060), safe (the
language model underneath does not move), and it uses the SAME honest gold-test protocol.

It writes to a SEPARATE dir (never clobbers mmbert-incident-ml). Promote a good run by
pointing EYENET_INCIDENT_MODEL_DIR at it.

Run (free ollama VRAM first if it OOMs):
    USE_TF=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        .venv/bin/python dataset/train_heads_frozen.py

    # or against a fresh export, more epochs since the head learns fast:
    .venv/bin/python dataset/train_heads_frozen.py --epochs 8 --lr 1e-3
"""

from __future__ import annotations

import argparse
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

import train_mmbert_ml as base  # noqa: E402  (reuse LABELS + load_silver/gold + auroc/support)

HERE = Path(__file__).parent
DEFAULT_START = str(HERE / "mmbert-incident-ml")       # the deployed model
DEFAULT_OUT = str(HERE / "mmbert-incident-ml-heads")   # PoC output, kept separate


def freeze_encoder(model: object) -> tuple[int, int]:
    """Freeze everything except the classification head. Returns (trainable, total) params.

    The head-only linear-probe: only ``classifier`` params keep gradients, so the encoder
    (mmBERT's multilingual representation) is preserved exactly."""
    trainable = 0
    total = 0
    for name, p in model.named_parameters():  # type: ignore[attr-defined]
        total += p.numel()
        head = name.startswith("classifier") or ".classifier" in name
        p.requires_grad = head
        if head:
            trainable += p.numel()
    return trainable, total


def build_splits() -> tuple[list[dict], list[dict]]:
    """Same split as train_mmbert_ml: silver pool + gold-train overrides, gold-test held out."""
    silver = base.load_silver()
    gold = base.load_gold()
    rng = np.random.default_rng(base.SEED)
    items = list(gold.items())
    rng.shuffle(items)
    cut = int(len(items) * (1 - base.GOLD_TEST_FRAC))
    gold_tr, gold_te = dict(items[:cut]), dict(items[cut:])
    pool = dict(silver)
    for t in gold_te:
        pool.pop(t, None)
    pool.update(gold_tr)
    tr = [{"text": t, "labels": v} for t, v in pool.items()]
    te = [{"text": t, "labels": v} for t, v in gold_te.items()]
    print(f"silver={len(silver)} gold={len(gold)} (gold-train={len(gold_tr)} gold-test={len(gold_te)})")
    print(f"train support    : {base.support(tr)}")
    print(f"GOLD-test support: {base.support(te)}")
    return tr, te


def report(probs: np.ndarray, y: np.ndarray) -> None:
    print("\n" + "=" * 64)
    print("HONEST eval: held-out HUMAN gold only (never trained)")
    print(f"{'label':<12} {'sup':>4} {'AUROC':>6} {'P@.5':>6} {'R@.5':>6}")
    for i, k in enumerate(base.LABELS):
        p_i, y_i = probs[:, i], y[:, i]
        pos = [float(v) for v, t in zip(p_i, y_i) if t == 1]
        neg = [float(v) for v, t in zip(p_i, y_i) if t == 0]
        pred_pos = p_i >= 0.5
        tp = int((pred_pos & (y_i == 1)).sum())
        prec = tp / max(1, int(pred_pos.sum()))
        rec = tp / max(1, int((y_i == 1).sum()))
        au = base.auroc(pos, neg)
        aus = "  n/a" if au != au else f"{au:6.3f}"
        print(f"{k:<12} {int(y_i.sum()):>4} {aus} {prec:6.2f} {rec:6.2f}")
    print("=" * 64)


def main(start: str, out: str, epochs: int, lr: float) -> None:
    tok = AutoTokenizer.from_pretrained(start)
    tr, te = build_splits()

    def tokz(batch):  # noqa: ANN001, ANN202
        return tok(batch["text"], truncation=True, max_length=128)

    ds_tr = Dataset.from_list(tr).map(tokz, batched=True)
    ds_te = Dataset.from_list(te).map(tokz, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(start)
    trainable, total = freeze_encoder(model)
    print(f"frozen-encoder head-only: trainable={trainable:,} / {total:,} "
          f"({100 * trainable / total:.2f}%)  start={start}")

    args = TrainingArguments(
        output_dir=out,
        num_train_epochs=epochs,
        per_device_train_batch_size=16,
        learning_rate=lr,            # head learns fast -> higher LR than the full retrain
        warmup_steps=20,
        weight_decay=0.01,
        bf16=torch.cuda.is_available(),
        gradient_checkpointing=False,  # no encoder grads to checkpoint
        logging_steps=25,
        save_strategy="no",
        report_to=[],
    )
    trainer = Trainer(model=model, args=args, train_dataset=ds_tr, processing_class=tok)
    trainer.train()

    model.eval()
    pred = trainer.predict(ds_te)
    probs = torch.sigmoid(torch.tensor(pred.predictions)).numpy()
    y = np.array([r["labels"] for r in te])
    report(probs, y)

    trainer.save_model(out)
    tok.save_pretrained(out)
    (Path(out) / "labels.json").write_text(json.dumps(base.LABELS), encoding="utf-8")
    # calibration.json is head-independent scaling; copy the deployed one so inference works.
    calib = Path(start) / "calibration.json"
    if calib.exists():
        (Path(out) / "calibration.json").write_text(calib.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nsaved -> {out}  (promote via EYENET_INCIDENT_MODEL_DIR={out})")


def _selfcheck() -> None:
    import torch.nn as nn

    m = nn.Module()
    m.encoder = nn.Linear(4, 4)      # stands in for the frozen mmBERT body
    m.classifier = nn.Linear(4, 6)   # the head we keep training
    trainable, total = freeze_encoder(m)
    assert not m.encoder.weight.requires_grad, "encoder must be frozen"
    assert m.classifier.weight.requires_grad, "head must stay trainable"
    # head params only: (4*6 + 6) = 30 trainable; total includes encoder (4*4+4=20) -> 50
    assert trainable == 30 and total == 50, (trainable, total)
    print("selfcheck ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START, help="starting model dir (the deployed model)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output dir (kept separate; never clobbers prod)")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        _selfcheck()
    else:
        main(a.start, a.out, a.epochs, a.lr)
