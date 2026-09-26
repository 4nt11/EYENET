# EYENET detection taxonomy (multi-label)

The detector is **multi-label**: a message can carry zero, one, or several labels.
"incident" as a single class was ambiguous ([[project_incidents_detection]]); this
splits it into crisp, independently-testable categories. Each label has a yes/no
definition a tired human can apply consistently.

Architecture: one shared mmBERT encoder with one sigmoid head per label (one forward
pass). Deterministic/syntactic categories (DDoS commands, cred combos) are handled by
the prefilter, not the model. `none` is implicit = no label fires.

---

## Labels

### `incident` — active compromise of a target
A claim or evidence that a specific target (org / company / gov / site) was actively
compromised. Past-tense **act**, specific victim. **DDoS takedown claims live here.**
- ✅ "HACKED BY X", defacements, "got root / shell uploaded", "we breached Y",
  "successfully breached Z", DDoS "TANGO DOWN"/"DOWN 3h" + check-host proof.
- ❌ posting data with no compromise claim (→ `leak`); *selling* access (→ `access-sale`);
  *future* plans (→ `actor-ops`); DDoS attack *commands* (→ prefilter, deterministic).

### `leak` — distribution of stolen data
Stolen/exposed data being made available, any type, **free or paid**.
- ✅ DB dumps, doxes, CC / account / credential lists, "download: [link]",
  breachforums thread drops, "X PERSONAL - 129k [Citizens]".
- ❌ infostealer ULP streams (→ `infostealer`); a breach *claim* with no data (→ `incident`).

### `infostealer` — the stealer-log ecosystem
Infostealer logs specifically: selling, giving, or advertising stealer channels /
dumps / ULPs.
- ✅ "fresh ULP", "cloud logs daily", `Pass: @channel`, `L0G$`, stealer-family dumps
  (redline/lumma/…), log-pack subscriptions.
- ❌ a one-off org DB leak (→ `leak`).

### `access-sale` — selling unauthorized access (IAB)
Offering or selling access to a system — initial-access brokering. NOT the data, the
door. (This is the category that resolves the old data-sale ambiguity.)
- ✅ "WTS webshell", "RDP to US corp $500", "i got office/SMTP 50k limit", "access to
  [org] for sale", cpanel/VPN/shell access listings.
- ❌ selling a finished dataset (→ `leak`); a confirmed compromise claim (→ `incident`).

### `actor-ops` — stated intent / plans / organization
A threat actor announcing intent, plans, or org activity — **not a completed act, not
chatter.** (Replaces the vague "threat-actor-news"; anchored to intent/org so it's testable.)
- ✅ announced future attacks ("Netz-SS deploying tomorrow", "we will hit X"),
  recruitment, alliances, leadership/official announcements, calls to action ("join the attack").
- ❌ completed breach/leak (their own labels); social chatter/greetings (→ `none`);
  outsiders' news *about* actors (not the actor talking).

### `tooling` — selling/offering offensive tools & services (crimeware)
The sale, rent, or advertisement of a reusable capability — a weapon or service, **not
access to a specific victim**. No named target = tooling; a named compromised target =
`access-sale`.
- ✅ webshell *scripts* / shell finders / checkers, DDoSaaS / booters / stressers /
  dstat panels / L7 methods, RATs, stealers-as-a-builder, malware/loaders, "CNC panel",
  cracking tools ("AUTO EXPLOIT / BRUTE FORCE"), WormGPT-style kits, "New Service Drop".
- ❌ selling access to a *named* site/org (→ `access-sale`); selling stolen data
  (→ `leak`); stealer *logs* themselves (→ `infostealer`); a DDoS attack *command*
  (→ prefilter); legit VPS/hosting rental with no abuse framing (→ `none`).
- No prefilter signal exists for this yet → **silver = 0, hand-labeled** (like `actor-ops`).

### `none` (implicit)
No label fires: greetings, logistics, negotiation without a deal, tool/bot telemetry,
memes, off-topic. The majority of real traffic.

---

## Overlap examples (multi-label is expected)
- "we breached X, DB here: [link]" → `incident` + `leak`
- "fresh ULP logs, sub $80 @cloud" → `infostealer`
- "selling RDP to a hacked gov site" → `access-sale` (+ `incident` if they claim they breached it)
- "WTS webshell — target.gov.br, DA37" → `access-sale` (named victim)
- "selling my private webshell builder + shell checker" → `tooling` (no victim, reusable)
- "New Service Drop: DDoS CNC panel, build your own booter" → `tooling`
- "Netz-SS deploys tomorrow, join us" → `actor-ops`
- "hi" / "gm" / "how much?" → `none`

## Deterministic (prefilter, not the model)
- DDoS **commands**: `/attack <target> 70 flood`, `/scan <url>`, `/flood`, `/ddos` — the
  `ddos_command` signal. Syntactic, 100% precise; no model needed.
- Cred combos, check-host proofs, onion mirrors, etc. — existing prefilter signals.
