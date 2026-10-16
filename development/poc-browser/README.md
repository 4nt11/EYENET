# poc-browser — human-browsing-over-Tor lab (standalone, NOT part of eyenet)

A throwaway lab to work out what actually evades a forum's **automated
anti-abuse** (pwnforums' `pf-auto`) **before** any of it touches the EYENET
collector. Nothing here imports eyenet; nothing here ships. Burn it when we know
the answer.

## The target shapes the toolkit (read this before adding libs)

pwnforums is reached as an **`http://…onion`** service:

- **No TLS to the forum.** Tor encrypts the transport; MyBB is served plain HTTP
  *inside* the tunnel. So **JA3 / TLS-fingerprint impersonation (curl-cffi,
  tls-client) has no surface here** — its whole value is clearnet HTTPS. We keep
  `curl-cffi` only for the HTTP-fidelity/header-order comparison and for future
  *clearnet* targets, not for the onion.
- **Tor users are Firefox.** Tor Browser is Firefox-ESR. Driving **Chromium**
  (undetected-chromedriver, puppeteer-stealth) over an onion is *itself*
  anomalous — Chrome-over-Tor barely exists. So the stealth browser here is
  **Playwright-Firefox tuned to look like Tor Browser**, not Chromium. (puppeteer
  is Node anyway — out of scope for a Python venv.)

## Measure before you build (the smart first step)

The real question `pf-auto` poses: **does it score client-side telemetry**
(mouse/scroll/timing/fingerprint JS → needs a real browser + human input), **or
is it purely server-side** (session IP, account age, request cadence → a browser
adds nothing and a clean warmed session + good pacing is the whole game)?

`recon.py` answers that empirically: load the onion, capture every network
request + every inline script, and flag any telemetry/fingerprinting beacons.
**Run it first.** If the forum ships no client-side scoring, the "big gun" is
behavioural (pacing + clean session), not a headless browser.

## Files

- `human.py` — dependency-free human-input primitives: **bézier** mouse paths,
  eased variable-speed moves, chunked human scrolling, reading-dwell and
  per-keystroke typing distributions. Runnable self-check: `python human.py`.
- `recon.py` — Playwright-Firefox over Tor; loads the onion as a guest and
  reports whether any client-side anti-abuse telemetry exists.
- `browse.py` — a human browse *session*: load → dwell → bézier-move to a board
  → click → read → scroll → next, over Tor, optionally with a warmed
  `storageState`. Logs a timeline + flags ban/challenge pages.

## Run

```bash
cd development/poc-browser
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
playwright install firefox          # downloads the browser
# Tor must be listening on 127.0.0.1:9050 (host tor, or `tor &`).
python human.py                     # offline self-check (no browser/Tor)
python recon.py  <onion-url>        # measure client-side defenses
python browse.py <onion-url> [storage_state.json]
```

## Deliberately deferred (ask if a result says we need them)

- **curl-cffi JA3 path** — moot on the http onion; keep for clearnet.
- **Chromium stealth (undetected-chromedriver)** — wrong engine for an onion;
  only worth it to A/B against Firefox, or for clearnet Cloudflare targets.
- **Residential/exit rotation, account-warming automation** — operator
  tradecraft; out of a browser PoC's scope.
