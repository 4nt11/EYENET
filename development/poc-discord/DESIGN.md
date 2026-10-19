# Discord collector — design notes (from the PoC)

Bridge from `probe.py` to the real `eyenet/collectors/discord/real.py`. Built off the
forum collector's shape: `ServiceBase`, identity pool, supervised process, plural from
day one. Mappings: guild/channel -> `group_`, user -> `actor`, message -> `message`
(snowflake as `evidence_ref`, idempotent), new `source.kind = DISCORD`. Embeds AND
attachments are ingested (drop-bots put the payload in embeds, not `content`).

## Cursor model — THE load-bearing rule: read UPWARD, never from genesis

Discord `GET /channels/{id}/messages` returns **newest-first**. A real client loads the
newest page, then pages BACKWARD as the user scrolls up. We replicate exactly that.

- **Backfill (history):** descending walk. Start from newest, then repeat with
  `before=<oldest_seen_id>` page by page, newest -> oldest. Persist `oldest_seen` per
  channel as the resumable backfill cursor. Stop when a page returns `< limit` rows
  (reached channel start) or hits a floor we already hold.
- **Live catch-up:** poll `after=<newest_seen_id>` to grab messages since the last sync,
  then advance `newest_seen`. This is also natural — the client does it on focus/reconnect.
- **FORBIDDEN (exposure):** `after=0`, `around=<first message>`, or deep-linking to
  message #1 to walk forward from the beginning. NO real client reads a channel bottom-up
  from genesis; that access pattern is a bot flare. Always read our way UP, never start at
  the literal beginning. See [[project_discord_collector_reads_upward]].

## Pacing — timing-based, not header-based

- User-token reads return **no** `x-ratelimit-*` headers (measured: only `cf-ray`,
  `cf-cache-status`, `via`, `x-discord-features`). Bot tokens get buckets; user tokens
  don't — by design, so self-bots can't pace cleanly. So a `429` is the ONLY feedback.
- Discord tolerates brisk sequential reads (the web client bursts `before` requests during
  a fast scroll; measured ~300-400ms/call rode clean). So: human-BRISK, not glacial.
  Backward walk in bursts with pauses that mimic scroll-and-read, never a tight loop racing
  to genesis.
- `429` = hard stop: back off, log `retry_after` + `x-ratelimit-scope`, widen cadence.
- One request in flight per identity. No concurrency. Active-hours windowing (same spirit
  as the forum crews' human-hours TODO) — no spare accounts, so a ban is unrecoverable.

## Fingerprint (from the PoC, keep coherent)

curl_cffi `impersonate="firefox147"` (closest to the mint browser FF157) + the exact
captured header set/order, `Accept-Encoding`/`Connection` omitted. `cf_clearance` is
TLS+UA+IP bound; remint via FlareSolverr on 403. UA <-> impersonate <-> cookie-mint
browser must stay the same Firefox, same rule as the forum TLS coupling.

## Discovery — Gateway (WS), NOT REST  [captured via Burp 2026-10-19]

Topology discovery happens over the Gateway WebSocket, not REST. Confirmed: the client
makes NO `/users/@me/guilds` or `/guilds/{id}/channels` calls (those are bot/OAuth-
flavored). Captured flow on `gateway.discord.gg`:

- Connect `wss://gateway.discord.gg/?encoding=json&v=9&compress=zlib-stream` (observed —
  this client uses JSON encoding, so NO ETF decoder needed).
- Compression is split:
  - server->client (HELLO, READY, dispatches): ONE continuous zlib/DEFLATE stream for the
    whole socket. Keep a single `zlib.decompressobj`, feed every server frame in order; a
    message ends at the `00 00 ff ff` flush. NOT per-frame, NOT gzip (the bytes just look
    like it).
  - client->server (IDENTIFY, heartbeats, op14): uncompressed JSON. IDENTIFY's own
    `compress:false` is PAYLOAD compression, separate from the transport zlib-stream.
- `HELLO` (op 10) -> heartbeat (op 1, `{"op":1,"d":<last_seq>}`) every ~41250 ms, jittered.
- `IDENTIFY` (op 2) — captured shape (token -> .env; the rest is the fingerprint to mirror):
  `capabilities:1734653`; `properties:{os,browser,browser_user_agent,browser_version,
  release_channel:"stable",client_build_number:641004,client_launch_id,launch_signature,
  client_app_state:"focused",gateway_connect_reasons:"AppSkeleton",installation_id,...}`;
  `presence:{status:"unknown",...}`; `compress:false`; `client_state:{guild_versions:{}}`;
  `qos_token`. Generate a FRESH `client_launch_id` + `launch_signature` per connect (new
  launch), keep `installation_id` stable. The client also emits a proprietary **op 41**
  init frame (`session_id` + `client_launch_id`) right after IDENTIFY — mirror it to look native.
- `READY` (op 0) + `READY_SUPPLEMENTAL` carry the tree: `guilds[]` (each with `channels[]`),
  `private_channels`, `read_states`. THAT is discovery -> map to `group_candidate`.
- Big guilds lazy-load via op 14 (channel/member ranges) on focus. Permission-filter to
  VIEW_CHANNEL before touching a channel.
- Resume on drop with session_id + last seq (op 6). NEVER a hot reconnect loop.

NATIVE decision (ANTI, keep it native — no no-compress shortcut): ride
`compress=zlib-stream` with the streaming inflate, AND run the WS over curl_cffi's
impersonated WebSocket (`Session.ws_connect(..., impersonate=<browser>)`) so the TLS
fingerprint matches.

COHERENCE RULE (corrected): one account can hold SEVERAL live sessions with DIFFERENT
browser fingerprints at once (ANTI runs Firefox + Chrome, both alive) — that is normal and
NOT a flag. The flag is mixing fingerprints WITHIN one session/token (a Firefox-minted
token presented with a Chrome IDENTIFY, etc.). So the collector picks ONE captured browser
profile and uses that session's token + cookie + super-properties + gateway IDENTIFY +
impersonate target TOGETHER, never Frankensteined. We captured the full Chrome-154 session
(IDENTIFY + cookies), so the collector IS the Chrome session: `impersonate="chrome150"`
(closest) on both REST and WS, `.env` = the Chrome token/cookie/super-props. The Firefox
session keeps living independently. IDENTIFY stays the ban-critical frame — mirror it
exactly; a malformed IDENTIFY or reconnect storm is the self-bot tell.

## Split of responsibilities

- **Gateway (WS):** discovery (READY tree), live events (MESSAGE_CREATE etc.), typing.
- **REST:** history backfill — the upward `before`-cursor walk (this IS what DevTools
  shows on scroll). Discovery output -> `group_candidate` for operator promotion.

## Data model — where every field lives (captured 2026-10-19)

The model is NOT one object. A field's meaning often needs a JOIN across sources, the
canonical example: `member.roles` is a list of role IDs that mean NOTHING without the
`guild.roles[]` definition table from READY. So the gateway is not just "discovery", it
is the LIVE EVENT CONSUMER; the collector keeps the socket open and ingests dispatches,
REST only backfills history.

| field | lives in | transport |
|---|---|---|
| id, timestamp, edited_timestamp | message object | REST list / WS `MESSAGE_CREATE` |
| author basics (username, global_name, bot) | message.author | REST / WS |
| content, embeds, attachments, mentions | message object | REST / WS |
| responded_to | `message.message_reference` + `referenced_message` | REST / WS |
| reactions (emoji + count) | message.reactions | REST / WS |
| reacted_by (WHO) | not on the message | **WS** `MESSAGE_REACTION_ADD/REMOVE` (or REST reactions endpoint) |
| role DEFINITIONS (id->name/color/perms/position) | `guild.roles[]` | **WS** `READY` |
| member.roles / nick / joined_at | guild member object | **WS** `GUILD_MEMBER_LIST_UPDATE` (op14) / `GUILD_MEMBER_UPDATE`, or REST profile's `guild_member` |
| user profile (bio/badges/connections/mutuals) | `/users/{id}/profile` | REST |
| presence / status | not on the message | **WS** `PRESENCE_UPDATE` |
| typing | — | **WS** `TYPING_START` |
| channels + names | `guild.channels[]` | **WS** `READY` |

Consequences for the collector:
- Discovery must capture `guild.roles` (not just channels) so `member.roles` resolves.
- The gateway leg runs an ongoing dispatch loop (`MESSAGE_CREATE`, `MESSAGE_REACTION_ADD`,
  `GUILD_MEMBER_LIST_UPDATE`, `PRESENCE_UPDATE`, `GUILD_MEMBER_UPDATE`), not a one-shot
  READY read. Send op14 (member-range subscribe) to force `GUILD_MEMBER_LIST_UPDATE`.
- Discord user id (snowflake) is a NEW hard-identifier axis. A guild member's resolved
  roles map to EYENET MembershipKind (OWNER/ADMIN/MEMBER) + a roles detail.
- Burp canNOT read server->client dispatches (zlib-stream compressed); our own inflating
  client (gateway.py) is the only way to see their shapes. Map the model from it.

## Scope

- In: Gateway discovery + live events; REST backfill (upward), embeds, attachments,
  resumable cursors.
- Out (noted): `POST .../ack` (mark-as-read — a real client acks what it reads; may
  matter for looking human later).
