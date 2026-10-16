#!/usr/bin/env python3
"""Benchmark incident classifier inference: CPU vs GPU, single vs batched.

Loads the trained model on each available device, warms it up (excluded), then times
single-message latency (batch=1) and batched throughput (batch 32 / 64) over real
messages. CUDA is async, so we synchronize around every timed section.

    USE_TF=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        .venv/bin/python dataset/bench_classifier.py
Free ollama's VRAM first if the GPU run OOMs.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ["USE_TF"] = "0"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

HERE = Path(__file__).parent
MODEL = str(HERE / "mmbert-incident-ml")
N = 256  # sample size for throughput


def load_texts() -> list[str]:
    rows = [
        json.loads(x)
        for x in (HERE / "eyenet_messages.jsonl").read_text("utf-8").splitlines()
        if x.strip()
    ]
    texts = [r["text"] for r in rows if r.get("text")]
    return texts[:N] if len(texts) >= N else (texts * (N // max(1, len(texts)) + 1))[:N]


def _sync(device: str) -> None:
    if device == "cuda":
        torch.cuda.synchronize()


def bench_device(device: str, texts: list[str]) -> dict[str, float]:
    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL).eval().to(device)

    def run(chunk: list[str]) -> None:
        x = tok(chunk, return_tensors="pt", truncation=True, max_length=128, padding=True).to(
            device
        )
        with torch.no_grad():
            _ = model(**x).logits
        _sync(device)

    # warmup (kernel compile / caches) — excluded from timing
    for _ in range(3):
        run(texts[:32])

    out: dict[str, float] = {}

    # single-message latency (batch=1)
    t0 = time.perf_counter()
    for t in texts[:64]:
        run([t])
    single_ms = (time.perf_counter() - t0) / 64 * 1000
    out["single_ms_per_msg"] = single_ms

    # batched throughput
    for bs in (32, 64):
        t0 = time.perf_counter()
        for i in range(0, len(texts), bs):
            run(texts[i : i + bs])
        elapsed = time.perf_counter() - t0
        out[f"batch{bs}_msgs_per_s"] = len(texts) / elapsed
        out[f"batch{bs}_ms_per_msg"] = elapsed / len(texts) * 1000
    return out


def main() -> None:
    texts = load_texts()
    devices = ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])
    print(f"messages: {len(texts)} | devices: {devices}")
    if "cuda" in devices:
        print(f"gpu: {torch.cuda.get_device_name(0)}")
    results = {}
    for dev in devices:
        print(f"\n--- {dev} (loading + warmup) ---")
        results[dev] = bench_device(dev, texts)
        for k, v in results[dev].items():
            print(f"  {k:<22} {v:8.2f}")

    if "cuda" in results and "cpu" in results:
        print("\n=== CPU vs GPU speedup (x faster on GPU) ===")
        for k in ("single_ms_per_msg", "batch32_ms_per_msg", "batch64_ms_per_msg"):
            print(f"  {k:<22} {results['cpu'][k] / results['cuda'][k]:6.1f}x")


if __name__ == "__main__":
    main()
