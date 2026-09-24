<script>
  import { onMount } from 'svelte';
  import QRCode from 'qrcode';
  import Button from '$lib/components/Button.svelte';
  import { sourceCtx, loadSources } from '$lib/source.svelte.js';
  import { qrCtx, startQrLogin, pollQrStatus, submitQrPassword, resetQr } from '$lib/identity.svelte.js';

  // QR login: provide api credentials + metadata, scan the QR with your Telegram
  // app (Settings > Devices > Link Desktop Device), enter 2FA if set, done. The
  // session is minted server-side and encrypted at rest — nothing is uploaded.
  let name = $state('');
  let sourceId = $state('');
  let apiId = $state('');
  let apiHash = $state('');
  let monitorGroups = $state('');
  let cooldown = $state('21600');
  let proxyUri = $state('');
  let notes = $state('');
  let password = $state('');
  let qrSvg = $state('');

  const tgSources = $derived(sourceCtx.list.filter((s) => s.platform === 'telegram'));
  const canStart = $derived(
    name.trim().length >= 1 && !!sourceId && apiId.trim() !== '' && apiHash.trim() !== '' && !qrCtx.busy
  );
  const started = $derived(!!qrCtx.loginId);
  const terminal = $derived(['complete', 'error', 'expired'].includes(qrCtx.status));

  onMount(() => {
    resetQr();
    loadSources();
  });

  // Render the current QR url as an inline SVG whenever it changes.
  $effect(() => {
    const url = qrCtx.qrUrl;
    if (!url) {
      qrSvg = '';
      return;
    }
    QRCode.toString(url, { type: 'svg', margin: 1, width: 240 })
      .then((s) => (qrSvg = s))
      .catch(() => (qrSvg = ''));
  });

  // Poll status while a login is in flight; stop on any terminal status.
  $effect(() => {
    if (!qrCtx.loginId || terminal) return;
    const t = setInterval(pollQrStatus, 2000);
    return () => clearInterval(t);
  });

  async function generate(e) {
    e.preventDefault();
    if (!canStart) return;
    await startQrLogin({
      name: name.trim(),
      source_id: sourceId,
      telegram_api_id: Number(apiId),
      telegram_api_hash: apiHash.trim(),
      monitor_groups: monitorGroups.split(',').map((s) => s.trim()).filter(Boolean),
      cooldown_seconds: cooldown.trim() ? Number(cooldown) : 21600,
      proxy_uri: proxyUri.trim() || null,
      notes: notes.trim() || null
    });
  }

  function submitPw(e) {
    e.preventDefault();
    if (password.trim()) submitQrPassword(password);
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb">
        <span class="group">System</span><span class="sep">/</span>
        <a class="slug-link" href="/identities">identities</a><span class="sep">/</span>
        <span class="slug">QR login</span>
      </div>
      <h1>Provision via QR login</h1>
    </div>
    <a class="back" href="/identities/provision">Upload a file instead</a>
  </div>

  <p class="lede">
    Scan a Telegram QR with your phone to mint a <strong>user</strong> session (not a bot).
    The session is minted server-side and encrypted at rest. Provide your API credentials,
    then scan from Telegram: Settings <span class="arrow">›</span> Devices <span class="arrow">›</span> Link Desktop Device.
  </p>

  {#if !started}
    <form class="card" onsubmit={generate}>
      <label class="fld"><span class="flabel">Source</span>
        <select class="fin" bind:value={sourceId}>
          <option value="" disabled>Select a Telegram source…</option>
          {#each tgSources as s}<option value={s.id}>{s.name} · {s.platform}</option>{/each}
        </select>
        {#if sourceCtx.loaded && !tgSources.length}<span class="hint">No Telegram sources yet — create one first.</span>{/if}
      </label>

      <label class="fld"><span class="flabel">Identity name</span>
        <input class="fin" type="text" bind:value={name} placeholder="tg_main" /></label>

      <div class="two">
        <label class="fld"><span class="flabel">Telegram API ID</span>
          <input class="fin" type="text" inputmode="numeric" bind:value={apiId} placeholder="123456" /></label>
        <label class="fld"><span class="flabel">Telegram API hash</span>
          <input class="fin" type="text" bind:value={apiHash} placeholder="0123abcd…" /></label>
      </div>

      <label class="fld"><span class="flabel">Monitor groups (optional, comma-separated)</span>
        <input class="fin" type="text" bind:value={monitorGroups} placeholder="@group_one, @group_two" /></label>

      <div class="two">
        <label class="fld"><span class="flabel">Cooldown seconds</span>
          <input class="fin" type="text" inputmode="numeric" bind:value={cooldown} placeholder="21600" /></label>
        <label class="fld"><span class="flabel">Proxy URI (optional)</span>
          <input class="fin" type="text" bind:value={proxyUri} placeholder="socks5://…" /></label>
      </div>

      <label class="fld"><span class="flabel">Notes (optional)</span>
        <input class="fin" type="text" bind:value={notes} placeholder="what this identity is for" /></label>

      {#if qrCtx.error}<p class="hint err">Failed: {qrCtx.error}</p>{/if}

      <div class="actions">
        <Button variant="primary" size="sm" type="submit" disabled={!canStart}>Generate QR</Button>
      </div>
    </form>
  {:else}
    <div class="card qr-card">
      {#if qrCtx.status === 'complete'}
        <p class="ok">✓ Provisioned. <a class="slug-link" href="/identities">Back to the pool</a></p>
      {:else if qrCtx.status === 'error' || qrCtx.status === 'expired'}
        <p class="err">Login {qrCtx.status}{qrCtx.detail ? `: ${qrCtx.detail}` : ''}.</p>
        <Button variant="primary" size="sm" onclick={resetQr}>Start over</Button>
      {:else if qrCtx.status === 'password_needed'}
        <p class="step">Two-factor password required.</p>
        <form class="pwform" onsubmit={submitPw}>
          <input class="fin" type="password" autocomplete="current-password" bind:value={password} placeholder="2FA password" />
          <Button variant="primary" size="sm" type="submit" disabled={qrCtx.busy || !password.trim()}>Submit</Button>
        </form>
        {#if qrCtx.error}<p class="hint err">{qrCtx.error}</p>{/if}
      {:else}
        <p class="step">Scan with Telegram › Settings › Devices › Link Desktop Device</p>
        <div class="qr">{@html qrSvg}</div>
        <p class="hint">Waiting for scan… the code refreshes automatically.</p>
        <Button variant="ghost" size="sm" onclick={resetQr}>Cancel</Button>
      {/if}
    </div>
  {/if}
</main>

<style>
  main { padding: 20px 24px; max-width: 720px; }
  .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
  .crumb { display: flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .slug-link, .back { color: var(--text-secondary); text-decoration: none; }
  .slug-link:hover, .back:hover { color: var(--accent); }
  h1 { margin: 4px 0 0; font-size: var(--fs-20); color: var(--text-body); }
  .lede { color: var(--text-secondary); font-size: var(--fs-13); line-height: 1.5; max-width: 60ch; }
  .arrow { color: var(--text-faint); }
  .card { display: flex; flex-direction: column; gap: 14px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px; margin-top: 8px; }
  .qr-card { align-items: center; text-align: center; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 560px) { .two { grid-template-columns: 1fr; } main { padding: 16px; } }
  .fld { display: flex; flex-direction: column; gap: 4px; }
  .flabel { font-family: var(--font-sans); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .fin { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 7px 10px; }
  .fin:focus { outline: none; border-color: var(--accent); }
  .fin::placeholder { color: var(--text-faint); }
  .qr { width: 240px; height: 240px; background: #fff; padding: 10px; border-radius: var(--radius); }
  .qr :global(svg) { width: 100%; height: 100%; }
  .step { font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); }
  .pwform { display: flex; gap: 8px; align-items: center; }
  .hint { font-family: var(--font-sans); font-size: var(--fs-11); color: var(--text-faint); }
  .hint.err, .err { color: var(--red-text); }
  .ok { color: var(--accent); }
  .actions { display: flex; justify-content: flex-end; margin-top: 4px; }
</style>
