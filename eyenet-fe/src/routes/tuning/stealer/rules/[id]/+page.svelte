<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { getRule, createRule, updateRule, deleteRule } from '$lib/stealerRulesApi.svelte.js';

  const MATCH_TYPES = ['folder', 'regex', 'delimiter', 'template', 'json', 'yaml', 'keyvalue', 'keyvalue_ini'];
  const LAYERS = ['container', 'content'];
  const NORMALIZE_VERBS = ['strip_whitespace', 'lowercase', 'uppercase', 'truncate', 'int_from_string', 'replace_re2', 'date_parse'];

  const slug = $derived($page.params.id);
  const isNew = $derived(slug === 'new');

  let families = $state([]);
  let rule = $state(blank());
  let rawMatch = $state('{}');
  let rawExtract = $state('{}');
  let loading = $state(true);
  let error = $state(null);
  let busy = $state(false);
  let saveMsg = $state(null);

  function blank() {
    return {
      id: '',
      version: 1,
      layer: 'content',
      family: 'combolist',
      priority: 100,
      description: '',
      path_glob: '',
      requires_container_family: '',
      match: { type: 'keyvalue', separator: ': ', strip_whitespace: true, requires_keys: [] },
      extract: { keys: {} },
      map: { rename: {}, _drop: [] },
      reject_patterns: [],
      normalize: []
    };
  }

  onMount(async () => {
    try {
      const fr = await fetch('/stealer-families.json');
      if (fr.ok) families = await fr.json();
      if (!isNew) {
        rule = { ...blank(), ...(await getRule(slug)) };
        rule.reject_patterns ??= [];
        rule.normalize ??= [];
      }
      rawMatch = JSON.stringify(rule.match ?? {}, null, 2);
      rawExtract = JSON.stringify(rule.extract ?? {}, null, 2);
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      loading = false;
    }
  });

  function onRawMatchInput(ev) {
    rawMatch = ev.currentTarget.value;
    try { rule.match = JSON.parse(rawMatch); } catch { /* keep typing */ }
  }
  function onRawExtractInput(ev) {
    rawExtract = ev.currentTarget.value;
    try { rule.extract = JSON.parse(rawExtract); } catch { /* keep typing */ }
  }

  async function onSave() {
    busy = true; saveMsg = null; error = null;
    try {
      const payload = cleanPayload(rule);
      if (isNew) await createRule(payload);
      else await updateRule(slug, payload);
      saveMsg = 'Saved.';
      if (isNew) goto(`/tuning/stealer/rules/${payload.id}`);
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      busy = false;
    }
  }

  async function onDelete() {
    if (isNew) return;
    if (!confirm(`Delete rule ${slug}? This writes to disk and cannot be undone through the UI.`)) return;
    busy = true; error = null;
    try {
      await deleteRule(slug);
      goto('/tuning/stealer');
    } catch (e) {
      error = String(e?.message ?? e);
      busy = false;
    }
  }

  function cleanPayload(r) {
    const out = { ...r };
    for (const k of ['description', 'path_glob', 'requires_container_family']) {
      if (!out[k]) delete out[k];
    }
    if (!out.reject_patterns?.length) delete out.reject_patterns;
    if (!out.normalize?.length) delete out.normalize;
    if (out.map && !Object.keys(out.map.rename ?? {}).length && !(out.map._drop ?? []).length) delete out.map;
    return out;
  }

  function moveStep(i, dir) {
    const n = (rule.normalize ?? []).slice();
    const j = i + dir;
    if (j < 0 || j >= n.length) return;
    [n[i], n[j]] = [n[j], n[i]];
    rule.normalize = n;
  }
  function addStep() {
    rule.normalize = [...(rule.normalize ?? []), { verb: 'strip_whitespace', field: '' }];
  }
  function removeStep(i) {
    rule.normalize = rule.normalize.filter((_, k) => k !== i);
  }

  function addReject() { rule.reject_patterns = [...(rule.reject_patterns ?? []), '']; }
  function removeReject(i) { rule.reject_patterns = rule.reject_patterns.filter((_, k) => k !== i); }
</script>

<div class="wrap">
  {#if loading}
    <div class="empty">Loading rule...</div>
  {:else if error && !rule.id}
    <div class="empty err">Load failed: <code>{error}</code></div>
  {:else}
    <div class="topbar">
      <a class="back" href="/tuning/stealer">&lt; Rules library</a>
      <h2>
        {#if isNew}New rule{:else}<span class="mono">{slug}</span>{/if}
      </h2>
      <div class="spacer"></div>
      {#if saveMsg}<span class="saved">{saveMsg}</span>{/if}
      {#if error}<span class="errbar" title={error}>{error}</span>{/if}
      <button class="btn-ghost" disabled={busy || isNew} onclick={onDelete}>Delete</button>
      <button class="btn-primary" disabled={busy} onclick={onSave}>{isNew ? 'Create' : 'Save'}</button>
    </div>

    <section class="layer meta">
      <header>
        <span class="n">.</span>
        <span class="label">Rule metadata</span>
        <span class="hint">id, layer, family, priority</span>
      </header>
      <div class="grid">
        <label>
          <span>Id</span>
          <input class="mono" type="text" bind:value={rule.id} disabled={!isNew} placeholder="lowercase_with_underscores" />
        </label>
        <label>
          <span>Layer</span>
          <select bind:value={rule.layer}>
            {#each LAYERS as l}<option value={l}>{l}</option>{/each}
          </select>
        </label>
        <label>
          <span>Family</span>
          <select class="mono" bind:value={rule.family}>
            {#each families as f}<option value={f.slug}>{f.slug}</option>{/each}
          </select>
        </label>
        <label>
          <span>Priority</span>
          <input class="mono" type="number" bind:value={rule.priority} />
        </label>
        <label class="wide">
          <span>Description</span>
          <input type="text" bind:value={rule.description} placeholder="one-sentence intent" />
        </label>
        <label>
          <span>Path glob</span>
          <input class="mono" type="text" bind:value={rule.path_glob} placeholder="**/*" disabled={rule.layer === 'container'} />
        </label>
        <label>
          <span>Requires container family</span>
          <select class="mono" bind:value={rule.requires_container_family} disabled={rule.layer === 'container'}>
            <option value="">(any)</option>
            {#each families as f}<option value={f.slug}>{f.slug}</option>{/each}
          </select>
        </label>
      </div>
    </section>

    <section class="layer">
      <header>
        <span class="n">01</span>
        <span class="label">Match</span>
        <span class="hint">which bytes qualify as a hit</span>
      </header>
      <div class="pad">
        <label class="wide">
          <span>Match type</span>
          <select class="mono" bind:value={rule.match.type}>
            {#each MATCH_TYPES as t}<option value={t}>{t}</option>{/each}
          </select>
        </label>
        <p class="hint-body">Each type carries its own body. For v1 the editor stores the body as raw JSON so advanced authors retain full control; per-type form controls land in v1.1.</p>
        <label class="wide">
          <span>Match body (JSON)</span>
          <textarea class="mono" rows="7" value={rawMatch} oninput={onRawMatchInput}></textarea>
        </label>
      </div>
    </section>

    <section class="layer">
      <header>
        <span class="n">02</span>
        <span class="label">Extract</span>
        <span class="hint">which fields to keep</span>
      </header>
      <div class="pad">
        <label class="wide">
          <span>Extract body (JSON)</span>
          <textarea class="mono" rows="7" value={rawExtract} oninput={onRawExtractInput}></textarea>
        </label>
        <label class="wide">
          <span>Reject patterns (RE2)</span>
          <div class="reject-list">
            {#each rule.reject_patterns as pat, i}
              <div class="reject-row">
                <input class="mono" type="text" value={pat} oninput={(e) => (rule.reject_patterns[i] = e.currentTarget.value)} placeholder="(?i)\bbanner\b" />
                <button class="btn-ghost sm" onclick={() => removeReject(i)}>Remove</button>
              </div>
            {/each}
            <button class="btn-ghost sm" onclick={addReject}>+ Add reject pattern</button>
          </div>
        </label>
      </div>
    </section>

    <section class="layer">
      <header>
        <span class="n">03</span>
        <span class="label">Normalize</span>
        <span class="hint">post-match string ops, applied in order</span>
      </header>
      <div class="pad">
        <div class="steps">
          {#each rule.normalize as step, i}
            <div class="step">
              <div class="idx mono">{String(i + 1).padStart(2, '0')}</div>
              <select class="mono" bind:value={step.verb}>
                {#each NORMALIZE_VERBS as v}<option value={v}>{v}</option>{/each}
              </select>
              <input class="mono" type="text" bind:value={step.field} placeholder="field" />
              {#if step.verb === 'truncate'}
                <input class="mono num" type="number" placeholder="max_len" bind:value={step.max_len} />
              {:else if step.verb === 'replace_re2'}
                <input class="mono" type="text" placeholder="pattern" bind:value={step.pattern} />
                <input class="mono" type="text" placeholder="replacement" bind:value={step.replacement} />
              {:else if step.verb === 'date_parse'}
                <select class="mono" bind:value={step.format}>
                  <option value="iso8601">iso8601</option>
                  <option value="rfc2822">rfc2822</option>
                  <option value="epoch_seconds">epoch_seconds</option>
                </select>
              {/if}
              <div class="row-actions">
                <button class="btn-ghost sm" onclick={() => moveStep(i, -1)} disabled={i === 0} title="Move up">^</button>
                <button class="btn-ghost sm" onclick={() => moveStep(i, 1)} disabled={i === (rule.normalize?.length ?? 0) - 1} title="Move down">v</button>
                <button class="btn-ghost sm" onclick={() => removeStep(i)}>Remove</button>
              </div>
            </div>
          {/each}
          <button class="btn-ghost sm add" onclick={addStep}>+ Add normalize step</button>
        </div>
      </div>
    </section>
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 16px; }

  .topbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
  }
  .topbar .back {
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase; color: var(--text-muted); text-decoration: none;
  }
  .topbar .back:hover { color: var(--accent-text); }
  .topbar h2 {
    margin: 0; font-family: var(--font-sans); font-size: var(--fs-16);
    font-weight: var(--fw-semibold); color: var(--text);
  }
  .topbar h2 .mono { font-family: var(--font-mono); color: var(--accent-text); }
  .topbar .spacer { flex: 1; }
  .topbar .saved { color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .topbar .errbar { color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-11); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .empty { padding: 40px; text-align: center; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-13); border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); }
  .empty.err { color: var(--red-text); border-color: var(--red-fill-strong); }
  .empty code { color: var(--text); background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }

  .layer { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .layer > header {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    background: var(--panel-2); border-bottom: 1px solid var(--border);
  }
  .layer > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .layer > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .layer > header .hint { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); flex: 1; }

  .meta .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 14px; }
  .meta label.wide { grid-column: span 4; }
  label { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  label span { text-transform: uppercase; letter-spacing: var(--tracking-label); font-size: var(--fs-11); color: var(--text-faint); font-weight: var(--fw-semibold); }
  input[type="text"], input[type="number"], select, textarea {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 6px 10px; color: var(--text);
    font-family: var(--font-sans); font-size: var(--fs-13);
    outline: none;
  }
  input.mono, select.mono, textarea.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); }
  input:disabled, select:disabled { opacity: .5; cursor: not-allowed; }

  .pad { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
  .hint-body { margin: 0; font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-muted); letter-spacing: var(--tracking-data); }

  textarea { resize: vertical; min-height: 120px; }

  .reject-list { display: flex; flex-direction: column; gap: 6px; }
  .reject-row { display: flex; gap: 6px; align-items: center; }
  .reject-row input { flex: 1; }

  .steps { display: flex; flex-direction: column; gap: 6px; }
  .step {
    display: grid;
    grid-template-columns: 36px 160px 1fr auto auto;
    gap: 8px; align-items: center;
    padding: 8px 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .step .idx { color: var(--text-faint); font-size: var(--fs-11); text-align: center; }
  .step .num { max-width: 100px; }
  .row-actions { display: flex; gap: 4px; }

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
  .btn-ghost.sm { padding: 3px 9px; font-size: var(--fs-11); }
  .btn-ghost.add { align-self: flex-start; margin-top: 4px; }
</style>
