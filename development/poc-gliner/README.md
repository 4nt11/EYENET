# poc-gliner

Measure whether GLiNER zero-shot is good enough to be EYENET's message-pipeline
entity extractor (org / threat-group / alias / malware / tool / location, ES+EN).
Deterministic entities (wallets/CVE/onion/IP/hash) are regex's job, not tested here.

## Run

```bash
! bash development/poc-gliner/sample.sh          # pull real sample from live docker DB (SENSITIVE)
pip install gliner                               # PoC-only dep
python development/poc-gliner/extract.py         # extract + stats + review dump + who/what/when demo
```

`extract.py --selfcheck` runs the aggregation tests with no model/torch.

## What "effective enough" means (decide BEFORE looking at output)

- **Coverage:** a healthy fraction of *forum* messages yield >=1 real entity.
  Telegram junk yielding nothing is expected, not a failure.
- **Precision:** eyeball `review.txt`, tally `y/(y+n)` per label. Rough bar: the
  fuzzy labels you care about (malware/tool/threat-group) clear ~0.8; aliases and
  org will be noisier.
- **The deliverable is real:** the who/what/when demo shows per-actor entities
  over time. If that table looks like intelligence, the approach works.

## If it fails

Per-label precision floor unreached (cf. the Spanish simhashes disabled in M6.5)
-> fine-tune a GLiNER head on mmBERT using the `dataset/` labeling loop. Defer
until measured — do NOT start there.
