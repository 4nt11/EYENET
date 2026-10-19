<script>
  import { onMount } from 'svelte';
  import Button from '$lib/components/Button.svelte';
  import { apiGet, apiPut } from '$lib/api.js';

  const NOAUTH = new Set([401, 403]);
  const MIB = 1048576;

  // The runtime knobs this page edits. `kind: 'mib'` edits in MiB (type 3, we store
  // 3*1048576 bytes); the API value is always the raw stored string (bytes / count).
  const KEYS = [
    {
      key: 'telegram.attachment_max_bytes',
      label: 'Attachment download size gate',
      unit: 'MiB',
      kind: 'mib',
      step: '0.1',
      // `d` is the MiB draft; show the exact byte count we'll store.
      hint: (d) =>
        `${Math.round((Number(d) || 0) * MIB).toLocaleString()} bytes per file. Photos are always pulled. Larger documents and video keep metadata + a t.me link only. 0 disables downloads entirely.`
    },
    {
      key: 'telegram.attachment_backfill_per_tick',
      label: 'Attachment backfill rate',
      unit: 'shells / tick',
      kind: 'count',
      step: '1',
      hint: (d) =>
        Number(d) > 0
          ? `HOT. Re-pulling up to ${d} historical attachment(s) per collector tick, through the live sessions. Set 0 to pause.`
          : 'HELD. Raise above 0 to start re-pulling historical attachment bytes. Ramp slowly (5-10) and watch the sessions.'
    }
  ];

  // Keep the input numeric no matter what is typed/pasted: a 'count' knob is digits only,
  // a 'mib' knob allows digits + a single decimal point. Everything else is stripped.
  function sanitizeNum(kind, raw) {
    const s = String(raw ?? '');
    if (kind === 'mib') return s.replace(/[^\d.]/g, '').replace(/(\.\d*)\./g, '$1');
    return s.replace(/\D/g, '');
  }

  // stored byte/count string <-> the draft shown in the input (MiB for a 'mib' knob).
  const toDraft = (it, stored) => (it.kind === 'mib' ? Number(stored) / MIB : stored);
  const toStored = (it, draft) =>
    it.kind === 'mib' ? String(Math.max(0, Math.round((Number(draft) || 0) * MIB))) : String(draft).trim();

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
            draft: toDraft(k, r.value),
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
      const r = await apiPut(`/v1/settings/${it.key}`, { value: toStored(it, it.draft) }, { auth: true });
      it.value = r.value;
      it.is_default = r.is_default;
      it.draft = toDraft(it, r.value);
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
                  type="text"
                  inputmode={it.kind === 'mib' ? 'decimal' : 'numeric'}
                  value={it.draft}
                  oninput={(e) => {
                    const clean = sanitizeNum(it.kind, e.currentTarget.value);
                    // Force the DOM back to the cleaned value even when the model is
                    // unchanged (type "5" then "a" both sanitize to "5" — Svelte would
                    // otherwise skip the re-render and leave the stray char on screen).
                    e.currentTarget.value = clean;
                    it.draft = clean;
                  }}
                  spellcheck="false"
                  autocomplete="off"
                />
                <span class="unit">{it.unit}</span>
              </label>
              <Button
                variant="primary"
                size="sm"
                disabled={it.saving || toStored(it, it.draft) === it.value}
                onclick={() => save(it)}
              >
                {it.saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
            <p class="hint">{it.hint(it.draft)}</p>
            {#if it.err}<p class="err">{it.err}</p>{/if}
            {#if it.saved && toStored(it, it.draft) === it.value}<p class="ok">Saved.</p>{/if}
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
