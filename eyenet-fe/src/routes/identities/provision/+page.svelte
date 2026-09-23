<script>
  import { onMount } from 'svelte';
  import Button from '$lib/components/Button.svelte';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { provisionCtx, provisionIdentity } from '$lib/identity.svelte.js';

  // Provision a new identity from an uploaded .session file (POST /v1/identities,
  // admin-only). Telegram is the only source with a file-based credential today;
  // the source dropdown is filtered to Telegram sources. The .session is
  // encrypted at rest server-side; it never comes back over the wire.
  let name = $state('');
  let sourceId = $state('');
  let apiId = $state('');
  let apiHash = $state('');
  let monitorGroups = $state('');
  let cooldown = $state('21600');
  let proxyUri = $state('');
  let notes = $state('');
  let files = $state(null);

  const tgSources = $derived(sourceCtx.list.filter((s) => s.platform === 'telegram'));
  const hasFile = $derived(!!files && files.length > 0);
  const ready = $derived(
    name.trim().length >= 1 &&
      !!sourceId &&
      hasFile &&
      apiId.trim() !== '' &&
      apiHash.trim() !== '' &&
      !provisionCtx.submitting
  );

  onMount(loadSources);

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    const fd = new FormData();
    fd.append('session', files[0]);
    fd.append('name', name.trim());
    fd.append('source_id', sourceId);
    fd.append('telegram_api_id', apiId.trim());
    fd.append('telegram_api_hash', apiHash.trim());
    if (monitorGroups.trim()) fd.append('monitor_groups', monitorGroups.trim());
    if (cooldown.trim()) fd.append('cooldown_seconds', cooldown.trim());
    if (proxyUri.trim()) fd.append('proxy_uri', proxyUri.trim());
    if (notes.trim()) fd.append('notes', notes.trim());

    const id = await provisionIdentity(fd);
    if (id) {
      name = '';
      apiId = '';
      apiHash = '';
      monitorGroups = '';
      proxyUri = '';
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
    <a class="back" href="/identities">Back to pool</a>
  </div>

  <p class="lede">
    Upload a Telegram <code>.session</code> file and its API credentials. The session is
    encrypted at rest; it is never returned or shown again. Mint the session out of band
    (your own machine) before uploading.
  </p>

  <form class="card" onsubmit={submit}>
    <label class="fld"><span class="flabel">Source</span>
      <select class="fin" bind:value={sourceId}>
        <option value="" disabled>Select a Telegram source…</option>
        {#each tgSources as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
      </select>
      {#if sourceCtx.loaded && !tgSources.length}<span class="hint">No Telegram sources yet — create one first.</span>{/if}
    </label>

    <label class="fld"><span class="flabel">Identity name</span>
      <input class="fin" type="text" bind:value={name} placeholder="tg_alpha" /></label>

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

    <div class="two">
      <label class="fld"><span class="flabel">Cooldown seconds</span>
        <input class="fin" type="number" bind:value={cooldown} placeholder="21600" /></label>
      <label class="fld"><span class="flabel">Proxy URI (optional)</span>
        <input class="fin" type="text" bind:value={proxyUri} placeholder="socks5://…" /></label>
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
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err { color: var(--red-text); }
  .hint.ok { color: var(--accent); }
  .actions { display: flex; justify-content: flex-end; margin-top: 4px; }
</style>
