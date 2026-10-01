<script>
  import { onMount } from 'svelte';
  import Button from '$lib/components/Button.svelte';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { provisionCtx, provisionIdentity } from '$lib/identity.svelte.js';

  // Provision a new identity from an uploaded credential (POST /v1/identities,
  // admin-only). Telegram takes a .session file + API creds; Forum takes a
  // browser session as Netscape cookies — pasted as text OR uploaded as a
  // cookies.txt file. The credential is encrypted at rest server-side; it never
  // comes back over the wire. Matrix uses QR/token, not this form.
  let name = $state('');
  let sourceId = $state('');
  // telegram
  let apiId = $state('');
  let apiHash = $state('');
  let monitorGroups = $state('');
  // forum
  let forumBaseUrl = $state('');
  let forumThreadUrls = $state('');
  let forumUserAgent = $state('');
  let cookiesText = $state('');
  // shared
  let cooldown = $state('21600');
  let proxyUri = $state('');
  let notes = $state('');
  let files = $state(null);

  // The stack's self-contained Tor SOCKS proxy (eyenet:tor service). An .onion
  // board is only reachable through it, so default to it automatically — until
  // the operator edits the proxy field, after which we never touch it again.
  const TOR_PROXY = 'socks5h://tor:9050';
  let proxyTouched = $state(false);
  const isOnion = $derived(/\.onion(?:[:/]|$)/i.test(forumBaseUrl.trim()));
  $effect(() => {
    // Managed only while untouched: .onion → Tor proxy, otherwise clear. Reads
    // proxyTouched + isOnion; writes proxyUri (not read here, so no loop).
    if (proxyTouched) return;
    proxyUri = isOnion ? TOR_PROXY : '';
  });

  const fileSources = $derived(
    sourceCtx.list.filter((s) => s.platform === 'telegram' || s.platform === 'forum')
  );
  const selected = $derived(sourceCtx.list.find((s) => s.id === sourceId));
  const kind = $derived(selected?.platform ?? '');
  const hasFile = $derived(!!files && files.length > 0);
  // Forum credential is present if pasted OR uploaded.
  const hasCookies = $derived(cookiesText.trim() !== '' || hasFile);
  const ready = $derived(
    name.trim().length >= 1 &&
      !!sourceId &&
      !provisionCtx.submitting &&
      (kind === 'telegram'
        ? hasFile && apiId.trim() !== '' && apiHash.trim() !== ''
        : kind === 'forum'
          ? hasCookies && forumBaseUrl.trim() !== ''
          : false)
  );

  onMount(loadSources);

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    const fd = new FormData();
    fd.append('name', name.trim());
    fd.append('source_id', sourceId);

    if (kind === 'telegram') {
      fd.append('session', files[0]);
      fd.append('telegram_api_id', apiId.trim());
      fd.append('telegram_api_hash', apiHash.trim());
      if (monitorGroups.trim()) fd.append('monitor_groups', monitorGroups.trim());
    } else if (kind === 'forum') {
      // Pasted text wins; else the uploaded cookies.txt. Either way it goes up as
      // the `session` file part the backend expects and validates (Netscape).
      const blob = cookiesText.trim()
        ? new File([cookiesText], 'cookies.txt', { type: 'text/plain' })
        : files[0];
      fd.append('session', blob);
      fd.append('forum_base_url', forumBaseUrl.trim());
      if (forumThreadUrls.trim()) fd.append('forum_thread_urls', forumThreadUrls.trim());
      if (forumUserAgent.trim()) fd.append('forum_user_agent', forumUserAgent.trim());
    }

    if (cooldown.trim()) fd.append('cooldown_seconds', cooldown.trim());
    if (proxyUri.trim()) fd.append('proxy_uri', proxyUri.trim());
    if (notes.trim()) fd.append('notes', notes.trim());

    const id = await provisionIdentity(fd);
    if (id) {
      name = '';
      apiId = '';
      apiHash = '';
      monitorGroups = '';
      forumBaseUrl = '';
      forumThreadUrls = '';
      forumUserAgent = '';
      cookiesText = '';
      proxyUri = '';
      proxyTouched = false; // re-enable auto-manage for the next identity
      notes = '';
      files = null;
    }
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb">
        <span class="group">System</span><span class="sep">/</span>
        <a class="slug-link" href="/identities">identities</a><span class="sep">/</span>
        <span class="slug">provision</span>
      </div>
      <h1>Provision identity</h1>
    </div>
    <a class="back" href="/identities/provision/qr">Use QR login instead</a>
  </div>

  <p class="lede">
    Telegram takes a <code>.session</code> file and API credentials. Forum takes a browser
    session as Netscape cookies — paste them or upload a <code>cookies.txt</code>. The
    credential is encrypted at rest; it is never returned or shown again. Mint it out of band
    (log in on your own machine) before uploading.
  </p>

  <form class="card" onsubmit={submit}>
    <label class="fld"><span class="flabel">Source</span>
      <select class="fin" bind:value={sourceId}>
        <option value="" disabled>Select a source…</option>
        {#each fileSources as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
      </select>
      {#if sourceCtx.loaded && !fileSources.length}<span class="hint">No Telegram or Forum sources yet — create one first.</span>{/if}
    </label>

    <label class="fld"><span class="flabel">Identity name</span>
      <input class="fin" type="text" bind:value={name} placeholder="alpha" /></label>

    {#if kind === 'telegram'}
      <label class="fld"><span class="flabel">Session file (.session)</span>
        <input class="fin file" type="file" accept=".session" onchange={(e) => (files = e.currentTarget.files)} />
      </label>

      <div class="two">
        <label class="fld"><span class="flabel">Telegram API ID</span>
          <input class="fin" type="number" bind:value={apiId} placeholder="123456" /></label>
        <label class="fld"><span class="flabel">Telegram API hash</span>
          <input class="fin" type="text" bind:value={apiHash} placeholder="0123abcd…" /></label>
      </div>

      <label class="fld"><span class="flabel">Monitor groups (optional, comma-separated)</span>
        <input class="fin" type="text" bind:value={monitorGroups} placeholder="@group_one, @group_two" /></label>
    {:else if kind === 'forum'}
      <label class="fld"><span class="flabel">Cookies (Netscape format — paste)</span>
        <textarea class="fin mono" rows="5" bind:value={cookiesText} placeholder="# Netscape HTTP Cookie File&#10;forum.example	FALSE	/	TRUE	9999999999	sid	abc123"></textarea>
        <span class="hint">Or upload a cookies.txt below. Pasted text takes priority.</span>
      </label>

      <label class="fld"><span class="flabel">Cookies file (cookies.txt, optional)</span>
        <input class="fin file" type="file" accept=".txt" onchange={(e) => (files = e.currentTarget.files)} />
      </label>

      <label class="fld"><span class="flabel">Forum base URL</span>
        <input class="fin" type="text" bind:value={forumBaseUrl} placeholder="https://forum.example — or http://xxx.onion for a Tor mirror" /></label>

      <label class="fld"><span class="flabel">Thread URLs (optional, comma-separated)</span>
        <input class="fin" type="text" bind:value={forumThreadUrls} placeholder="Thread-slug--123, Thread-other--456" /></label>

      <label class="fld"><span class="flabel">User-Agent (optional)</span>
        <input class="fin" type="text" bind:value={forumUserAgent} placeholder="Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0" />
        <span class="hint">Match the browser that exported these cookies (Tor Browser for an .onion board) — a UA mismatch vs the session is a ban signal. Blank = Tor Browser default.</span></label>
    {:else if sourceId}
      <p class="hint">This source kind can't be provisioned from this form.</p>
    {/if}

    <div class="two">
      <label class="fld"><span class="flabel">Cooldown seconds</span>
        <input class="fin" type="number" bind:value={cooldown} placeholder="21600" /></label>
      <label class="fld"><span class="flabel">Proxy URI (optional)</span>
        <input class="fin" type="text" bind:value={proxyUri} oninput={() => (proxyTouched = true)} placeholder="socks5h://tor:9050 for an .onion board" />
        {#if isOnion && !proxyTouched}<span class="hint">Auto-set to the stack's Tor proxy for this .onion board — edit to override.</span>{/if}</label>
    </div>

    <label class="fld"><span class="flabel">Notes (optional)</span>
      <input class="fin" type="text" bind:value={notes} placeholder="what this identity is for" /></label>

    {#if provisionCtx.error}<p class="hint err">Failed: {provisionCtx.error}</p>{/if}
    {#if provisionCtx.ok}<p class="hint ok">{provisionCtx.ok}</p>{/if}

    <div class="actions">
      <Button variant="primary" size="sm" type="submit" disabled={!ready}>Provision identity</Button>
    </div>
  </form>
</main>

<style>
  main { padding: 20px 24px; max-width: 720px; }
  .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .crumb .sep { color: var(--text-faint); }
  .slug-link, .back { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover, .back:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .lede { color: var(--text-secondary); font-size: var(--fs-13); line-height: 1.5; max-width: 60ch; }
  .lede code { font-family: var(--font-mono); font-size: var(--fs-12); }
  .card { display: flex; flex-direction: column; gap: 14px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; margin-top: 8px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 560px) { .two { grid-template-columns: 1fr; } main { padding: 16px; } }
  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }
  .fin.file { padding: 6px 8px; }
  .fin.mono { font-family: var(--font-mono); font-size: var(--fs-12); resize: vertical; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err { color: var(--red-text); }
  .hint.ok { color: var(--accent); }
  .actions { display: flex; justify-content: flex-end; margin-top: 4px; }
</style>
