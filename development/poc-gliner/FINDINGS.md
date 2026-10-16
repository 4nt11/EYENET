# poc-gliner findings

Question: can we add structured entity extraction (who/what/when) over the
message corpus, and is GLiNER the right engine? Measured on 2000 real forum
messages + 500 telegram, pulled from the live DB (`sample.sh`), GPU (RTX 5060),
isolated venv (`development/poc-gliner/.venv`, no system/`.venv` pollution).

## What we measured

1. GLiNER zero-shot (`urchade/gliner_multi-v2.1`), several label sets.
2. Gazetteer (dictionary) match for the closed-set entities (MITRE ATT&CK, then
   abuse.ch ThreatFox with the key).
3. Ground-truth grep, to separate "tool missed it" from "it is not in the text".

## Results

### GLiNER by label

| label | outcome |
|---|---|
| breached company / organization | WINNER. ~80%+ precision zero-shot (Cybertek, AXA, Oxfam, Woundtech, Sysco, IFAPME, lettutor.com). Maps cleanly to actor x time. |
| location | noise. Country codes, CSV headers (Zip, City), combolist columns. Dropped. |
| organization (generic) | half pronouns (We, Our company). Dropped in favour of the breach-victim framing. |
| person alias / handle | low value from prose; structured fields do this better. Dropped. |
| malware | hallucinates (roblox, gmail, KeePassXC). Failed twice. |
| threat actor / hacking group | low volume, mostly junk (Lmao, the stealer). |

Label competition is real: removing `hacking tool` pushed its noise into
`malware` (56 to 135). The label set is a soft competition, not independent.

### Gazetteer (malware + threat group)

- ATT&CK: 596 groups, 703 malware. Forum match after stoplisting common-word
  collisions (play, royal, proton...): 6 hits, all ShinyHunters, 100% precise.
  Zero malware.
- ThreatFox (authenticated, 5722 families): made malware WORSE, not better. Real
  malware family names are common words (chrome, gecko, fargo, roboto, trump,
  santa), so a bigger real dictionary carpet-bombs false positives (1198 hits,
  almost all false). Reverted to keyless ATT&CK-only.

### Ground truth (grep over 2000 forum messages)

redline 0, lumma 0, raccoon 0, vidar 0, stealc 0, cobalt strike 0, lockbit 1,
botnet 0. Generic words barely register (ransomware 2, stealer 2, malware 2,
exploit 9).

The corpus is commodity cybercrime (carding, payment fraud, breach-dump
trading). It does not name malware. No dictionary fixes an absent target.

## Verdict

| entity | decision |
|---|---|
| breached org / victim | GLiNER, single open-set label. Ship it. |
| threat group | gazetteer (ATT&CK). Catches catalogued crews precisely; forum-native crews are in no external catalog and would need corpus-mining. |
| malware | drop. Not present in this corpus (proven three ways), and any real dictionary floods false positives. Revisit only if a malware-rich feed is ingested. |
| wallets / CVE / onion / handle | regex + checksum / structured field, never a model. |

GLiNER goes from 6 labels to 1. That is the PoC working: it killed 5 labels and
one whole entity class before any production code.

## Production shape (if greenlit)

- GLiNER breached-org as a plural sensor, locale path first, batched inference,
  GPU. Entities become graph nodes + MENTIONED edges (actor_id, message_id,
  sent_at), reusing the existing graph layer for the who/what/when query.
- ATT&CK group gazetteer as a cheap deterministic pass alongside.
- Backfill: one-shot resumable batch job over the corpus (GPU, a few hours), then
  streaming on new messages.

## Open items

- 384-token cap: GLiNER's processor truncates at ~384 tokens. Long forum threads
  lose their tail. Production needs sliding-window chunking.
- Forum-native crew names need corpus-mining (frequency + human curation), not an
  external list.
- Threshold + the heavier `knowledgator` model were not swept; breached-org
  already clears the bar, so deferred.

## Repro

```
bash development/poc-gliner/sample.sh                 # pull sample (SENSITIVE, live DB)
development/poc-gliner/.venv/bin/python development/poc-gliner/extract.py --source-kind forum
python development/poc-gliner/build_gazetteer.py      # ATT&CK; set ABUSE_CH_APIKEY to add ThreatFox
python development/poc-gliner/match_gazetteer.py --source-kind forum
```
