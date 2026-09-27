# Hierarchical incident taxonomy (v2, locked leaf set)

Status: agreed leaf set, pre-implementation. The live model is still the flat 6 heads
(`dataset/mmbert-incident-ml/labels.json`). This is the target the data work builds toward.

## Organizing principle

Group by **threat-actor business model / criminal purpose**, NOT by technical medium.
The flat 6 heads conflate distinct businesses (e.g. `access_sale` bundled real Initial
Access Brokerage with SIP/SMS fraud services). Medium-based tagging smears one activity
across markets; purpose-based tagging keeps them separate and reads true to an analyst.

The canonical illustration is **DDoS**, which is three different things by business model:

| what | leaf |
|---|---|
| "we took down X" (a brag) | OFFENSIVE_EVENT.ddos_attack |
| selling an L7 script / dstat tool to run yourself | SERVICE_MARKET.crimeware_tooling |
| a booter subscription / managed stresser | SERVICE_MARKET.crime_aas |

## The leaf set

```
OFFENSIVE_EVENT            (an action / brag, not a sale)
├── defacement            HACKED BY, Greetz, mass-deface
├── ddos_attack           attack claims / brags ("took down X")
└── intrusion             breach claim, shell uploaded, got root

DATA_MARKET               (stolen data as the product)
├── breach_dump           DB dumps, PII, victim.zip            (was: leak)
├── credentials           combos, User:/Pw:, hash lists
└── stealer_logs          infostealer output, log clouds       (was: infostealer)

ACCESS_MARKET             (footholds into victim orgs as the product)
└── iab_corporate         RDP/VPN/webshell/cpanel/domain-admin  ← the TRUE access_sale

SERVICE_MARKET            (capabilities / services for rent)
├── crimeware_tooling     COMMODITY weapons you run yourself: crypters/FUD, stealer-
│                         builders, RATs, loaders, DDoS scripts, L7/dstat tools,
│                         checkers/scanners, panels ("some dude selling FUDs")
├── crime_aas             AS-A-SERVICE / affiliate: RaaS, DDoSaaS (booter subs), MaaS.
│                         Higher intel value than commodity tooling — its own leaf.
├── telecom_abuse         voice/SMS channel: SIP/VoIP trunks, caller-ID spoofing, bulk SMS
├── phishing_delivery     email/phishing infra: SMTP senders, webmailers, SendGrid,
│                         mass mailers, scampages / phishing kits   (was mis-bucketed access_sale)
└── fraud_ops            OTP bots, cashout, muling, bank-drops, card shops

ACTOR_OPS                 (the org's meta-business)
├── recruiting
├── alliance
└── crew_ops
```

## Multi-label rulings (a message can carry several leaves)

- **bulk SMS → telecom_abuse AND fraud_ops** — it is the channel (telecom) and its purpose
  is smishing (fraud). Both fire.
- **OTP bots → fraud_ops only** — rides the phone channel but exists to defeat 2FA; a fraud
  operation, not a channel sale.
- **DDoS**: script/tool → crimeware_tooling; booter subscription/DDoSaaS → crime_aas;
  "we took X down" → ddos_attack. Split by delivery model, not by the word "ddos".
- **PhaaS** (phishing-as-a-service kits): default phishing_delivery; revisit if volume
  justifies pulling it into crime_aas.

## Mapping the current 6 heads onto the leaves

| current head | destination(s) | mechanical? |
|---|---|---|
| incident | OFFENSIVE_EVENT.{defacement, ddos_attack, intrusion} | NO — needs sub-classification |
| leak | DATA_MARKET.breach_dump (+ credentials) | mostly |
| infostealer | DATA_MARKET.stealer_logs | yes |
| access_sale | ACCESS_MARKET.iab_corporate OR telecom_abuse OR phishing_delivery OR fraud_ops | NO — needs re-inspection/split |
| tooling | crimeware_tooling OR crime_aas | NO — needs commodity-vs-aaS split |
| actor_ops | ACTOR_OPS.{recruiting, alliance, crew_ops} | mostly |

The three NO rows are the bulk of the human labeling work: the old flat heads bundled
sub-markets that now split. The operator relabel + export loop is the mechanism.

## Model shape

Start **flat multi-label over the ~16 leaves** (one sigmoid per leaf, same architecture),
and derive the coarse business-model label by OR-ing a parent's children. Only move to a
true conditional hierarchy (coarse head gating per-parent fine heads) if flat-over-leaves
underperforms on the rare leaves. Rare leaves that stay data-starved keep their deterministic
prefilter/rule catch (the SIP lesson) rather than a stillborn model head.

## Data work sequence (what "work the data" means)

1. **Lock `labels_v2`** = this leaf set (the contract every layer keys off).
2. **Update the label surface**: `labels.json` head order, `SIG2LABEL` (prefilter signal →
   leaf), FE relabel chips (`INCIDENT_LABELS`) + endpoint taxonomy validation.
3. **Remap existing gold** (`*.mllabels.jsonl`): mechanical renames where 1:1; queue the
   `incident` / `access_sale` / `tooling` rows for human re-inspection (they split).
4. **Rebootstrap silver** via `bootstrap_silver.py` with the new `SIG2LABEL`.
5. **Train + calibrate** on the leaf labels; roll up to coarse for reporting.
