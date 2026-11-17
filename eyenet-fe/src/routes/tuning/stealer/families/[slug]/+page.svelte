<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import Dropdown from '$lib/components/Dropdown.svelte';
  import { getFamily, createFamily, updateFamily, deleteFamily } from '$lib/stealerFamiliesApi.svelte.js';

  const STATUS_OPTS = ['active', 'new', 'dormant', 'retired', 'suspected'].map((v) => ({ v, l: v }));

  const slug = $derived($page.params.slug);
  const isNew = $derived(slug === 'new');

  let family = $state(blank());
  let loading = $state(true);
  let error = $state(null);
  let busy = $state(false);
  let saveMsg = $state(null);

  function blank() {
    return {
      slug: '',
      name: '',
      status: 'new',
      first_seen_year: new Date().getFullYear(),
      aliases: [],
      signature_files: [],
      loaders: [],
      distribution_channels: [],
      references: [],
      notes: ''
    };
  }

  onMount(async () => {
    try {
      if (!isNew) {
        family = { ...blank(), ...(await getFamily(slug)) };
        for (const k of ['aliases', 'signature_files', 'loaders', 'distribution_channels', 'references']) {
          family[k] ??= [];
        }
      }
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      loading = false;
    }
  });

  const cleanFamily = $derived.by(() => {
    const out = { ...family };
    for (const k of ['aliases', 'signature_files', 'loaders', 'distribution_channels', 'references']) {
      if (!Array.isArray(out[k]) || out[k].length === 0) delete out[k];
    }
    if (!out.notes?.trim()) delete out.notes;
    if (!out.first_seen_year) delete out.first_seen_year;
    return out;
  });
  const jsonPreview = $derived(JSON.stringify(cleanFamily, null, 2));

  async function onSave() {
    busy = true; saveMsg = null; error = null;
    try {
      if (isNew) await createFamily(cleanFamily);
      else await updateFamily(slug, cleanFamily);
      saveMsg = 'Saved.';
      if (isNew) goto(`/tuning/stealer/families/${cleanFamily.slug}`);
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      busy = false;
    }
  }

  async function onDelete() {
    if (isNew) return;
    if (!confirm(`Delete family ${slug}? Fails loudly if any rule still references it.`)) return;
    busy = true; error = null;
    try {
      await deleteFamily(slug);
      goto('/tuning/stealer/families');
    } catch (e) {
      error = String(e?.message ?? e);
      busy = false;
    }
  }

  function listAdd(key) { family[key] = [...(family[key] ?? []), '']; }
  function listRemove(key, i) { family[key] = family[key].filter((_, k) => k !== i); }
  function listSet(key, i, v) { const a = (family[key] ?? []).slice(); a[i] = v; family[key] = a; }

  function refAdd() { family.references = [...(family.references ?? []), { title: '', url: '' }]; }
  function refRemove(i) { family.references = family.references.filter((_, k) => k !== i); }
</script>

<div class="page">
  {#if loading}
    <div class="empty">Loading family...</div>
  {:else if error && !family.slug}
    <div class="empty err">Load failed: <code>{error}</code></div>
  {:else}
    <div class="topbar">
      <a class="back" href="/tuning/stealer/families">&lt; Family catalog</a>
      <span class="status-chip s-{family.status}">{family.status}</span>
      <h2>
        {#if isNew}New family{:else}<span class="mono">{slug}</span>{/if}
      </h2>
      <div class="spacer"></div>
      {#if saveMsg}<span class="saved">{saveMsg}</span>{/if}
      {#if error}<span class="errbar" title={error}>{error}</span>{/if}
      <button class="btn-ghost" disabled={busy || isNew} onclick={onDelete}>Delete</button>
      <button class="btn-primary" disabled={busy} onclick={onSave}>{isNew ? 'Create' : 'Save'}</button>
    </div>

    <div class="cols">
      <div class="editor">
        <section class="layer">
          <header>
            <span class="n">.</span>
            <span class="label">Identity</span>
            <span class="hint">slug drives the enum; name is the display label</span>
          </header>
          <div class="grid">
            <label>
              <span>Slug</span>
              <input class="mono" type="text" bind:value={family.slug} disabled={!isNew} placeholder="lumma" />
            </label>
            <label>
              <span>Name</span>
              <input type="text" bind:value={family.name} placeholder="Lumma Stealer" />
            </label>
            <label>
              <span>Status</span>
              <Dropdown options={STATUS_OPTS} bind:value={family.status} minWidth="100%" />
            </label>
            <label>
              <span>First seen year</span>
              <input class="mono" type="number" bind:value={family.first_seen_year} placeholder="2022" />
            </label>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">01</span>
            <span class="label">Aliases</span>
            <span class="hint">other names the family is known by</span>
          </header>
          <div class="pad">
            {#each family.aliases as item, i}
              <div class="row">
                <input class="mono flex" type="text" value={item} oninput={(e) => listSet('aliases', i, e.currentTarget.value)} placeholder="LummaC2" />
                <button class="btn-ghost sm" onclick={() => listRemove('aliases', i)}>x</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={() => listAdd('aliases')}>+ Add alias</button>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">02</span>
            <span class="label">Signature files</span>
            <span class="hint">file/dir names an operator looks for to identify a drop</span>
          </header>
          <div class="pad">
            {#each family.signature_files as item, i}
              <div class="row">
                <input class="mono flex" type="text" value={item} oninput={(e) => listSet('signature_files', i, e.currentTarget.value)} placeholder="System.txt or Clients/" />
                <button class="btn-ghost sm" onclick={() => listRemove('signature_files', i)}>x</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={() => listAdd('signature_files')}>+ Add file</button>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">03</span>
            <span class="label">Loaders</span>
            <span class="hint">what malware loader delivers this family</span>
          </header>
          <div class="pad">
            {#each family.loaders as item, i}
              <div class="row">
                <input class="mono flex" type="text" value={item} oninput={(e) => listSet('loaders', i, e.currentTarget.value)} placeholder="SmokeLoader" />
                <button class="btn-ghost sm" onclick={() => listRemove('loaders', i)}>x</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={() => listAdd('loaders')}>+ Add loader</button>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">04</span>
            <span class="label">Distribution channels</span>
            <span class="hint">where the family is sold or distributed</span>
          </header>
          <div class="pad">
            {#each family.distribution_channels as item, i}
              <div class="row">
                <input class="flex" type="text" value={item} oninput={(e) => listSet('distribution_channels', i, e.currentTarget.value)} placeholder="Russian forums (XSS, exploit.in)" />
                <button class="btn-ghost sm" onclick={() => listRemove('distribution_channels', i)}>x</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={() => listAdd('distribution_channels')}>+ Add channel</button>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">05</span>
            <span class="label">References</span>
            <span class="hint">operator-chosen primary sources</span>
          </header>
          <div class="pad">
            {#each family.references as ref, i}
              <div class="refrow">
                <input type="text" bind:value={ref.title} placeholder="eSentire TRU breakdown" />
                <input class="mono" type="text" bind:value={ref.url} placeholder="https://..." />
                <button class="btn-ghost sm" onclick={() => refRemove(i)}>x</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={refAdd}>+ Add reference</button>
          </div>
        </section>

        <section class="layer">
          <header>
            <span class="n">06</span>
            <span class="label">Notes</span>
            <span class="hint">operator notes · formats, distinguishers, history</span>
          </header>
          <div class="pad">
            <textarea bind:value={family.notes} rows="8" placeholder="Free-form markdown-ish notes. Formats, distinguishers vs neighbouring families, incident history."></textarea>
          </div>
        </section>
      </div>

      <aside class="jsonpanel">
        <header>
          <span class="n">.</span>
          <span class="label">Family YAML preview</span>
          <span class="hint">live, write to disk on save</span>
        </header>
        <pre class="json mono">{jsonPreview}</pre>
      </aside>
    </div>
  {/if}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 16px; }

  .topbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
  }
  .topbar .back { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-muted); text-decoration: none; }
  .topbar .back:hover { color: var(--accent-text); }
  .topbar h2 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text); }
  .topbar h2 .mono { font-family: var(--font-mono); color: var(--accent-text); }
  .topbar .spacer { flex: 1; }
  .topbar .saved { color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .topbar .errbar { color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-11); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .status-chip {
    padding: 3px 8px; border: 1px solid var(--border); border-radius: var(--radius-sm);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase; color: var(--text-muted); background: var(--surface);
  }
  .status-chip.s-active   { color: var(--accent-text); border-color: var(--accent); background: var(--accent-fill); }
  .status-chip.s-new      { color: var(--accent-text); border-color: var(--accent-text); background: var(--accent-fill); }
  .status-chip.s-dormant  { color: var(--text-muted); }
  .status-chip.s-retired  { color: var(--text-faint); border-color: var(--border); }
  .status-chip.s-suspected { color: var(--red-text); border-color: var(--red-fill-strong); background: var(--red-fill); }

  .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: flex-start; }
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }

  .editor { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

  .jsonpanel {
    position: sticky; top: 12px;
    border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--panel); overflow: hidden;
    max-height: calc(100vh - 120px); display: flex; flex-direction: column;
  }
  .jsonpanel > header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .jsonpanel > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .jsonpanel > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .jsonpanel > header .hint { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); letter-spacing: var(--tracking-data); }
  .json {
    margin: 0; padding: 14px;
    font-family: var(--font-mono); font-size: var(--fs-12);
    letter-spacing: var(--tracking-data); color: var(--text);
    background: var(--surface);
    overflow: auto; flex: 1;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
  }

  .empty { padding: 40px; text-align: center; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-13); border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); }
  .empty.err { color: var(--red-text); border-color: var(--red-fill-strong); }
  .empty code { color: var(--text); background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }

  .layer { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .layer > header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--panel-2); border-bottom: 1px solid var(--border); }
  .layer > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .layer > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .layer > header .hint { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); flex: 1; }

  .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 14px; }
  label { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  label > span { text-transform: uppercase; letter-spacing: var(--tracking-label); font-size: var(--fs-11); color: var(--text-faint); font-weight: var(--fw-semibold); }
  input[type="text"], input[type="number"], textarea {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 6px 10px; color: var(--text);
    font-family: var(--font-sans); font-size: var(--fs-13);
    outline: none; min-width: 0;
  }
  input.mono, textarea.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  input.flex { flex: 1; }
  input:focus, textarea:focus { border-color: var(--accent); }
  input:disabled { opacity: .5; cursor: not-allowed; }
  textarea { resize: vertical; min-height: 120px; }

  .pad { padding: 14px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: flex; gap: 6px; align-items: center; }
  .refrow { display: grid; grid-template-columns: 1fr 2fr auto; gap: 6px; align-items: center; }

  .btn-primary {
    background: var(--accent); color: white; border: 1px solid var(--accent);
    border-radius: var(--radius); padding: 6px 14px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    cursor: pointer; transition: background 120ms ease;
  }
  .btn-primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
  .btn-primary:disabled { opacity: .45; cursor: not-allowed; }
  .btn-ghost {
    background: transparent; color: var(--text-muted); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 6px 12px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    cursor: pointer;
  }
  .btn-ghost:hover:not(:disabled) { background: var(--panel-2); color: var(--text); }
  .btn-ghost:disabled { opacity: .35; cursor: not-allowed; }
  .btn-ghost.sm { padding: 3px 9px; font-size: var(--fs-11); align-self: flex-start; }
</style>
