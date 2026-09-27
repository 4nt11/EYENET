# Hierarchical incident taxonomy (proposal)

Status: proposal / sketch. The live taxonomy is still the flat 6 heads
(`development/incident-taxonomy.md`, `dataset/mmbert-incident-ml/labels.json`).
This documents the target structure and the interim steps toward it.

## Why

The flat 6 heads conflate distinct threat-actor **business models**. The most acute
case: `access_sale` bundles true **Initial Access Brokerage** (selling footholds into
victim orgs: RDP/VPN/webshell/cpanel/domain-admin) with **fraud-enablement services**
(SIP trunking, bulk SMS, caller-ID spoofing, SMTP senders). An analyst would never call
a SIP-trunk seller an initial access broker. Selling "access to routes/numbers" is a
*consequence* of the telecom-abuse business model, not initial access brokerage.

A head is cheap in params but expensive in labels (see the head-count analysis: a head
with <~30 positives is theater). A flat layer of many rare heads starves them. A
hierarchy lets rare leaves borrow strength from a high-support parent.

## Level 1 — business model (what is being transacted or done)

1. **OFFENSIVE_EVENT** — an action / brag, not a sale.
2. **DATA_MARKET** — stolen data as the product.
3. **ACCESS_MARKET** — footholds into victim orgs as the product (true IAB).
4. **SERVICE_MARKET** — capabilities / tools / services for rent (not data, not a foothold).
5. **ACTOR_OPS** — the org's meta-business (recruiting, alliances, crews).

## Level 2 — market leaves

```
OFFENSIVE_EVENT
├── defacement          (HACKED BY, Greetz, mass-deface)
├── ddos                (attack claims / brags)
└── intrusion_claim     (shell uploaded, got root, breached)

DATA_MARKET
├── breach_dump         (DB dumps, PII, victim.zip)        ← was: leak
├── credentials         (combos, User:/Pw:, hash lists)
└── stealer_logs        (infostealer output, log clouds)   ← was: infostealer

ACCESS_MARKET
└── iab_corporate       (RDP/VPN/webshell/cpanel/domain-admin access to an org)
                        ← the TRUE meaning of access_sale

SERVICE_MARKET
├── crimeware_tooling   (booters, stealer-builders, crypters, botnets, panels)  ← was: tooling
├── telecom_abuse       (SIP/VoIP trunking, bulk SMS, caller-ID spoofing,
│                        SMTP/SendGrid senders, sender-ID)   ← was mis-bucketed as access_sale
└── fraud_service       (OTP bots, cashout, muling, bank-log services)

ACTOR_OPS
├── recruiting
├── alliance
└── crew_ops
```

## Mapping the current 6 heads onto the hierarchy

| current head | hierarchy destination |
|---|---|
| incident | OFFENSIVE_EVENT (all leaves) |
| leak | DATA_MARKET.breach_dump (+ credentials) |
| infostealer | DATA_MARKET.stealer_logs |
| access_sale | **SPLIT** → ACCESS_MARKET.iab_corporate (keep) **+** SERVICE_MARKET.telecom_abuse (extract) |
| tooling | SERVICE_MARKET.crimeware_tooling |
| actor_ops | ACTOR_OPS |

The one structural change is splitting `access_sale`. Everything else is a rename plus a
parent grouping.

## Why the hierarchy earns its keep here

- **Coarse heads are high-support and easy** (SERVICE_MARKET fires on lots of data → good
  AUROC), so the model is confident about the parent even when a leaf is rare.
- **Rare leaves refine only within a confident parent**, so `telecom_abuse` and
  `fraud_service` are not data-starved flat heads competing against `incident`.
- **The label reads true to an analyst**: `SERVICE_MARKET > telecom_abuse` says "fraud
  service", not "someone is brokering access to a company".

## Interim steps (before the model gets new heads)

1. **[DONE]** Prefilter `telecom_abuse` signal → maps to `tooling` today (the closest
   existing head) in `SIG2LABEL`. When the `telecom_abuse` leaf lands, remap the signal to
   it — no prefilter rewrite needed.
2. **[KNOWN RESIDUAL]** `access_material` in the prefilter still contains bare `smtp`, so
   SMTP-sender ads still fire `access_sale`. This is the same conflation. Resolve when the
   `telecom_abuse` head lands: move SMTP-*sender* context to `telecom_abuse` and keep
   SMTP-*shell/relay access* under `iab_corporate`. Not changed now to avoid a behavior +
   recalibration change out of scope for the prefilter addition.
3. Implementation order when heads land: relabel gold under the new leaves (the operator
   relabel + export loop already does this) → retrain with the split labels → recalibrate.
   Empirically, a novel subclass like `telecom_abuse` needs real labeled volume before the
   model learns it; until then the prefilter signal is the reliable catch.
