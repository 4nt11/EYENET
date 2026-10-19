# poc-discord

Prototype for an EYENET Discord **read** collector. PoC-then-implement: validate the
REST pull + measure the rate-limit envelope here, *then* build the real collector off
the forum collector's shape (ServiceBase, identity pool, `_timing_presets`).

## Run

```sh
cp env.example .env            # then fill DISCORD_TOKEN (+ cookie etc. — see below)
../../.venv/bin/python probe.py --selfcheck     # offline: header order sanity
../../.venv/bin/python probe.py                 # one 10-msg page, dump headers+timing
../../.venv/bin/python probe.py --limit 50
../../.venv/bin/python probe.py --before <snowflake>   # walk older (backfill shape)
```

Use the repo venv (`../../.venv`) — it has `curl_cffi` 0.16.3.

## .env fields

| var | what |
|-----|------|
| `DISCORD_TOKEN` | Authorization header value, verbatim. User tokens have **no** `Bearer ` prefix. |
| `DISCORD_COOKIE` | Full Cookie header as a single `k=v; k=v` string (NOT a Netscape jar). Must include `cf_clearance`. |
| `DISCORD_SUPER_PROPERTIES` | The base64 `X-Super-Properties` from the same session. |
| `DISCORD_INSTALLATION_ID` | `X-Installation-Id` from the same session. |
| `DISCORD_CHANNEL_ID` / `DISCORD_GUILD_ID` | Prototype target (prefilled). |

All of these are per-account / per-browser credentials. `.env` is gitignored; keep it that way.

## Why curl_cffi + Firefox impersonation

`cf_clearance` is bound to the TLS fingerprint (JA3/JA4) + UA of the browser that minted
it. `httpx`/`requests` emit an OpenSSL "Python" ClientHello, so Cloudflare voids the
clearance and the account gets flagged. `curl_cffi` with `impersonate="firefox147"`
(closest target to FF157) speaks TLS as Firefox and the clearance holds. Same tradecraft
as `eyenet/collectors/forum`. For a strict wall, pin FF157's exact cipher/sigalg list via
curl_cffi `extra_fp` (capture them first) — not needed while the clearance is fresh.

`Accept-Encoding` and `Connection` are intentionally dropped from the header set
(decode-trap + illegal on HTTP/2); see the comment in `probe.py`.

## When cf_clearance expires (403)

Remint with the FlareSolverr container (already running, `FLARESOLVERR_URL`):
`POST {FLARESOLVERR_URL}` `{"cmd":"request.get","url":"https://discord.com/","maxTimeout":60000}`
then copy the returned `cf_clearance` + UA back into `.env`. FlareSolverr solves the
challenge in a real browser; it is for minting clearance, NOT for the authenticated API
call (that stays on curl_cffi).

## The chunk model (confirmed)

`GET /channels/{id}/messages?limit=<=100[&before=<snowflake>]` returns a newest-first
page. Snowflake `before`/`after` is the cursor = the **backfill** walk (snowflakes encode
the timestamp, so no `now()` recency trap). Live/forward would be the Gateway WebSocket.

## Scope / next

- In scope: REST read, pagination, rate-limit measurement.
- Out of scope (noted, not built): Gateway WS for live `MESSAGE_CREATE` + typing
  indicators (`who is typing, when` — cute, low priority); `POST /channels/{id}/messages/{id}/ack`
  = mark-as-read (a real client acks; may matter for looking human later).
- Pacing: reuse poc-browser's jitter/timing philosophy (human-like inter-request delays),
  NOT its mouse/bezier/click sim — this is REST, not a rendered client.
- Mapping to the real collector: channel -> `group_`, user -> `actor`, message ->
  `message` (idempotent on the snowflake as `evidence_ref`), new `source.kind = DISCORD`,
  identity-pool entry with `discord_`-prefixed config fields.
