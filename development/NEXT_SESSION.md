# EYENET — session handoff (2026-09-26): INCIDENT DETECTION subsystem

Start here, then read
`~/.claude/projects/-home-anti-Projects-EYENET/memory/MEMORY.md` — especially
`project_incidents_detection`, `project_laya_finetune_experiment`,
`incident_prefilter_field_signals`, `feedback_small_llm_prompt_structure`.

> This weekend was NOT the M9 API backlog — it was a new subsystem: **detecting
> threat-actor incidents in monitored channels.** (The old M9/clearance-API handoff
> is still valid backlog; it just isn't what we've been doing. See git history.)

---

## What this is

A **3-tier detection cascade** over monitored-group messages, plus the ML pipeline
to train/measure it. Motivated by `project_clients_under_attack_monitoring_priority`.

```
message
  └─ 1. PREFILTER  eyenet/incidents/prefilter.py   (pure RE2, deterministic, ~0ms)
  │     structural signals: deface_banner, ddos_command, check_host, cred_combo,
  │     leak_host/label, stealer_logs, cloud_pass, access_material, pii_schema,
  │     compromise_confirmed, homoglyph-fold, … (29 gold tests, all field-grounded)
  └─ 2. mmBERT     dataset/mmbert-incident/         (fine-tuned jhu-clsp/mmBERT-base)
  │     semantic, multilingual, ~16ms on the RTX 5060. Beats raw laya on real data.
  └─ 3. qwen (LLM) via ollama, ONLY for the uncertain band  (reason-first prompt)
```
laya (`convaiinnovations/laya`) was the original stage-2 idea — GREAT zero-shot on
curated data (0.93) but **collapses on raw traffic (0.65 AUROC, flags 74%)**. The
fine-tuned mmBERT replaced it. laya is still installed; don't rely on it standalone.

---

## THE BIG PIVOT (last thing we did): multi-label taxonomy

"incident" as one binary was ambiguous (is a data-sale an incident?). We split it.
**Source of truth: `development/incident-taxonomy.md`.** 5 labels + implicit `none`,
MULTI-LABEL (one mmBERT encoder, one sigmoid head per label; overlap expected):

- `incident` — active compromise of a target (breach/intrusion/deface / DDoS-takedown CLAIM)
- `leak` — distribution of stolen data (dumps/doxes/CC/accounts, free or paid)
- `infostealer` — stealer-log ecosystem (ULP/cloud logs/stealer channels)
- `access-sale` — selling unauthorized access (IAB: webshell/RDP/VPN) [resolved the sale ambiguity]
- `actor-ops` — stated intent/plans/org (future attacks, recruitment, alliances, calls to action)
- `none` — chatter/tools/logistics (the ~88% majority)

DDoS **commands** (`/attack <t> flood`) = deterministic prefilter (`ddos_command`),
not the model. **The current mmBERT is still the OLD binary model** — the multi-label
model is NOT trained yet. That's the next job.

---

## Honest results so far (binary model, real data)

- **Blind random human-labeled eval (231 msgs): mmBERT AUROC 0.893, acc 0.87,
  precision 0.67, recall 0.82.** ← the only deck-safe number. laya on same: 0.65.
- Per-channel discrimination works: chatter channels quiet (Jacuzzi 2%), attack
  channels loud (Dark storm 93%, JAX7 62%); overall 23% flag ≈ true base rate (21%).
- DO NOT quote the silver held-out ~0.99 — its labels are heuristic-derived (circular).
- Human gold labels directly killed FP classes (e.g. Khmer border-conflict NEWS the
  model flagged at 1.0; @handle chatter; proxy-checker tool).

---

## File map (everything lives in `dataset/`, code in `eyenet/incidents/`)

| file | what |
|---|---|
| `eyenet/incidents/prefilter.py` | the RE2 structural gate (+ `tests/unit/incidents/`) |
| `dataset/data.md` | hand-collected real brag samples (ANTI's, `---` separated) |
| `dataset/gen_corpus.py` | ollama synthetic generator (multi-model, provenance-tagged) |
| `dataset/build_dataset.py` | redact (substitution, not `<TAGS>`) + 70/30 split → train/test.jsonl |
| `dataset/train_mmbert.py` | fine-tune mmBERT-base (FRESH from base each run, folds gold) |
| `dataset/eval_mmbert.py` | per-case eval on held-out |
| `dataset/decision_log.py` | full per-msg log (group/prefilter/laya_p/mmbert_p/text) → decision_log.jsonl |
| `dataset/poc_cascade.py` | 3-tier PoC (prefilter+laya+qwen) |
| `dataset/labeler.html` | **LOCAL offline multi-tag UI** (keys 1-5, 0=none, exports .mllabels.jsonl) |
| `dataset/harvest_real.py` | silver labels from decision_log (POS=pf+model agree, NEG=short-no-signal) |
| `dataset/bootstrap_silver.py` | prefilter-families → silver MULTI-labels → `silver_multilabel.jsonl` |
| `dataset/make_eval_sample.py` | random BLIND sample for unbiased eval |
| `dataset/eyenet_messages.jsonl` | 8264 real msgs extracted from the docker DB |
| `dataset/*.labels.jsonl` / `*.mllabels.jsonl` | human labels (gold) |

---

## Environment — CRITICAL, these cost hours

- **venv `pip` SCRIPT is broken** (stale shebang → /home/anti/Tools/…). ALWAYS use
  `.venv/bin/python -m pip`, never `.venv/bin/pip`.
- **torch 2.11.0+cu128** installed for the RTX 5060 (Blackwell sm_120). A default
  torch has no sm_120. `USE_TF=0` on every laya/transformers run (TF import deadlock).
- **GPU = RTX 5060, 8GB VRAM.** OOM is real: before any training/inference, free
  ollama's resident model (`for m in $(ollama ps|awk 'NR>1{print $1}'); do ollama stop "$m"; done`).
  Training uses `max_len 128` + `gradient_checkpointing=True` + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
- **ollama** is the local LLM host (qwen for stage-3, uncensored models for gen).
  ANTI may stop it; if calls get `Connection refused`, it's down — ask him.
- **transformers 5.x**: `warmup_ratio`→`warmup_steps`; `Trainer(tokenizer=)`→`processing_class=`.
- **Sensitive-source guard**: bulk-exporting message bodies from the docker DB trips
  the auto-mode classifier. ANTI must approve (accept-edits) or run it via `!`.
- **Data is real threat-actor/victim content.** Keep it LOCAL. `labeler.html` is
  offline by design (no CDN, no publish). Do NOT publish artifacts with this data.
- Run scripts backgrounded (`run_in_background`), NOT double-backgrounded (a `&`
  inside run_in_background gets killed when the wrapper exits — cost us a run).
- `ripwire eyenet --for="…"` and the turbovec EYENET index are available for search.

---

## NEXT TASK (recommended order)

1. **Multi-label relabel + train — THE main job.**
   - ANTI labels in `labeler.html` loading `dataset/silver_multilabel.jsonl` (silver
     tags pre-fill toggles; he confirms/corrects). Exports `*.mllabels.jsonl`.
   - Watch: `infostealer` silver was only 8 (likely under-fired) and `actor_ops`=0
     by design (semantic) — both need human labels. Sale/leak boundary too.
   - Then adapt `train_mmbert.py` → **multi-label**: `problem_type="multi_label_classification"`,
     `num_labels=5`, BCE loss, per-label sigmoid. Eval → **per-category** precision/recall.
2. **Honest eval**: `dataset/eval_sample.jsonl` (250 random blind) — score the trained
   model on it for a per-category deck number. Re-pull with make_eval_sample.py if stale.
3. **Known FN gaps** (from the blind-eval audit): bare off-platform links
   (`x.com/…/status`, shell URLs) — the model can't read a URL's destination. That's
   a future **link-enrichment** capability, not a fix. `actor-ops` framing-evasion
   ("I rarely leak databases, I will release…") needs training examples.
4. **Only after the model's good**: wire it into EYENET proper — the `incident`
   storage table + service + operator triage feed (passive, no in-group footprint).
   This is still slice 3+ of `project_incidents_detection`; the model came first.

---

## How to resume
```bash
cd /home/anti/Projects/EYENET && git status && git log --oneline -6
sed -n '1,60p' development/incident-taxonomy.md          # the 5 labels
.venv/bin/python -m pytest tests/unit/incidents/ -q --no-cov -p no:randomly   # 29 green
ls -la dataset/*.jsonl dataset/labeler.html dataset/*.py # the pipeline
# GPU work: USE_TF=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True .venv/bin/python dataset/<script>.py
# free ollama VRAM first if training/infer OOMs
```
Nothing here is committed yet — it's all working-tree in `dataset/` + `eyenet/incidents/`
+ `development/incident-taxonomy.md`. Decide with ANTI what to commit vs keep local
(the real-message jsonl and model dir should NOT be committed — sensitive/large).
