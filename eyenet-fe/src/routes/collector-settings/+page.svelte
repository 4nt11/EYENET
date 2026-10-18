<script>
  import { onMount } from 'svelte';
  import Button from '$lib/components/Button.svelte';
  import { apiGet, apiPut } from '$lib/api.js';

  const NOAUTH = new Set([401, 403]);

  // The runtime knobs this page edits. `kind: 'bytes'` renders a MiB hint; the stored
  // value is always the raw string the API validates (bytes / integer count).
  const KEYS = [
    {
      key: 'telegram.attachment_max_bytes',
      label: 'Attachment download size gate',
      unit: 'bytes',
      kind: 'bytes',
      hint: (v) =>
        `${(Number(v) / 1048576).toFixed(2)} MiB per file. Photos are always pulled. Larger documents and video keep metadata + a t.me link only. 0 disables downloads entirely.`
    },
    {
      key: 'telegram.attachment_backfill_per_tick',
      label: 'Attachment backfill rate',
      unit: 'shells / tick',
      kind: 'count',
      hint: (v) =>
        Number(v) > 0
          ? `HOT. Re-pulling up to ${v} historical attachment(s) per collector tick, through the live sessions. Set 0 to pause.`
          : 'HELD. Raise above 0 to start re-pulling historical attachment bytes. Ramp slowly (5-10) and watch the sessions.'
    }
  ];

  let items = $state([]);
  let loaded = $state(false);
  let status = $state(0);

  onMount(load);

  async function load() {
    try {
      items = await Promise.all(
        KEYS.map(async (k) => {
          const r = await apiGet(`/v1/settings/${k.key}`, { auth: true });
          return {
            ...k,
            value: r.value,
            is_default: r.is_default,
            description: r.description,
            draft: r.value,
            saving: false,
            err: null,
            saved: false
          };
        })
      );
    } catch (e) {
      status = e.status ?? 0;
    } finally {
      loaded = true;
    }
  }

  async function save(it) {
    it.saving = true;
    it.err = null;
    it.saved = false;
    try {
      const r = await apiPut(`/v1/settings/${it.key}`, { value: String(it.draft).trim() }, { auth: true });
      it.value = r.value;
      it.is_default = r.is_default;
      it.draft = r.value;
      it.saved = true;
    } catch (e) {
      it.err = e.message ?? 'save failed';
    } finally {
      it.saving = false;
    }
  }
</script>

<main>
  <div class="head">
    <div>
      <div class="crumb"><span class="group">System</span><span class="sep">/</span><span class="slug">collector settings</span></div>
      <h1>Collector Settings</h1>
    </div>
  </div>

  <div class="body">
    <p class="lead">
      Runtime knobs the collectors re-read live (no redeploy). Changes take effect within
      about a minute. These are admin-only (<code>admin:settings</code>).
    </p>

    {#if items.length}
      <div class="cards">
        {#each items as it (it.key)}
          <section class="card">
            <div class="card-head">
              <div>
                <h2>{it.label}</h2>
                <code class="key">{it.key}</code>
              </div>
              {#if it.is_default}<span class="pill">default</span>{/if}
            </div>
            <p class="desc">{it.description}</p>
            <div class="editor">
              <label>
                <input
                  type="number"
                  min="0"
                  bind:value={it.draft}
                  spellcheck="false"
                />
                <span class="unit">{it.unit}</span>
              </label>
              <Button
                variant="primary"
                size="sm"
                disabled={it.saving || String(it.draft).trim() === String(it.value).trim()}
                onclick={() => save(it)}
              >
                {it.saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
            <p class="hint">{it.hint(it.draft)}</p>
            {#if it.err}<p class="err">{it.err}</p>{/if}
            {#if it.saved && String(it.draft).trim() === String(it.value).trim()}<p class="ok">Saved.</p>{/if}
          </section>
        {/each}
      </div>
    {:else if loaded && NOAUTH.has(status)}
      <p class="note">Collector settings need an admin token (<code>admin:settings</code>). Sign in with the right scope.</p>
    {:else if loaded}
      <p class="note">Collector settings unavailable (<code>/v1/settings</code> did not respond).</p>
    {:else}
      <p class="note">Loading…</p>
    {/if}
  </div>
</main>

<style>
  main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--black); }
  .head { flex: 0 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .crumb { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); }
  .group { color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .sep { color: var(--text-faint); }
  .slug { color: var(--accent-text); }
  h1 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-22); font-weight: var(--fw-semibold); color: var(--text); line-height: var(--lh-tight); }
  .body { flex: 1; min-height: 0; overflow: auto; padding: 16px 20px; }
  .lead { margin: 0 0 16px; font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text-body); line-height: var(--lh-normal); }
  .lead code, .note code, .hint code { color: var(--accent-text); font-family: var(--font-mono); }
  .cards { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
  .card { padding: 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  h2 { margin: 0 0 4px; font-family: var(--font-sans); font-size: var(--fs-15); font-weight: var(--fw-semibold); color: var(--text); }
  .key { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .pill { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); border: 1px solid var(--border); border-radius: var(--radius); padding: 2px 7px; }
  .desc { margin: 10px 0 12px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-body); line-height: var(--lh-normal); }
  .editor { display: flex; align-items: center; gap: 10px; }
  .editor label { display: flex; align-items: center; gap: 8px; }
  .editor input { width: 160px; font-family: var(--font-mono); font-size: var(--fs-13); padding: 6px 8px; background: var(--black); border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); }
  .unit { font-family: var(--font-mono); font-size: var(--fs-11); text-transform: uppercase; letter-spacing: var(--tracking-label); color: var(--text-faint); }
  .hint { margin: 10px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); line-height: var(--lh-normal); }
  .note { margin: 12px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .err { margin: 10px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--critical, #e06c5a); }
  .ok { margin: 10px 0 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent-text); }
</style>
