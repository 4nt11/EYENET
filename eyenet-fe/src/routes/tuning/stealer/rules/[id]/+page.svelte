<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { getRule, createRule, updateRule, deleteRule } from '$lib/stealerRulesApi.svelte.js';

  const MATCH_TYPES = ['folder', 'regex', 'delimiter', 'template', 'json', 'yaml', 'keyvalue', 'keyvalue_ini'];
  const LAYERS = ['container', 'content'];
  const NORMALIZE_VERBS = ['strip_whitespace', 'lowercase', 'uppercase', 'truncate', 'int_from_string', 'replace_re2', 'date_parse'];
  const DATE_FORMATS = ['iso8601', 'rfc2822', 'epoch_seconds'];

  const slug = $derived($page.params.id);
  const isNew = $derived(slug === 'new');

  let families = $state([]);
  let rule = $state(blank());
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
        rule.match ??= { type: 'keyvalue' };
        rule.extract ??= {};
      }
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      loading = false;
    }
  });

  // When match.type changes, reset the type-specific body shape AND the
  // extract shape (each match type drives a different extract vocab).
  let lastType = $state('keyvalue');
  $effect(() => {
    const t = rule.match?.type;
    if (!t || t === lastType) return;
    rule.match = seedMatchFor(t);
    rule.extract = seedExtractFor(t);
    lastType = t;
  });

  function seedMatchFor(t) {
    switch (t) {
      case 'folder':       return { type: t, requires: [], forbids: [], optional: [], min_score: 0 };
      case 'regex':        return { type: t, pattern: '', multiline: false, dotall: false };
      case 'delimiter':    return { type: t, separator: '\t', min_columns: 0, skip_blank: true, skip_comment_prefix: '' };
      case 'template':     return { type: t, template: '', multiline: false };
      case 'json':         return { type: t, requires_keys: [] };
      case 'yaml':         return { type: t, requires_keys: [] };
      case 'keyvalue':     return { type: t, separator: ': ', strip_whitespace: true, requires_keys: [] };
      case 'keyvalue_ini': return { type: t, requires_sections: [] };
      default:             return { type: t };
    }
  }
  function seedExtractFor(t) {
    switch (t) {
      case 'folder':                   return {};
      case 'regex': case 'template':   return { fields: [] };
      case 'delimiter':                return { columns: {} };
      case 'json': case 'yaml':        return { paths: {} };
      case 'keyvalue': case 'keyvalue_ini': return { keys: {} };
      default:                         return {};
    }
  }

  // ------- payload cleanup for save + side-panel preview -------
  const cleanRule = $derived.by(() => cleanPayload(rule));
  const jsonPreview = $derived(JSON.stringify(cleanRule, null, 2));

  function cleanPayload(r) {
    const out = { ...r };
    for (const k of ['description', 'path_glob', 'requires_container_family']) {
      if (!out[k]) delete out[k];
    }
    if (!out.reject_patterns?.length) delete out.reject_patterns;
    if (!out.normalize?.length) delete out.normalize;
    if (out.map) {
      const hasRename = Object.keys(out.map.rename ?? {}).length > 0;
      const hasDrop = (out.map._drop ?? []).length > 0;
      if (!hasRename && !hasDrop) delete out.map;
      else out.map = {
        ...(hasRename ? { rename: out.map.rename } : {}),
        ...(hasDrop ? { _drop: out.map._drop } : {})
      };
    }
    // Strip empty optional lists from the match body.
    if (out.match) {
      const m = { ...out.match };
      for (const k of ['requires', 'forbids', 'optional', 'requires_keys', 'requires_sections']) {
        if (Array.isArray(m[k]) && m[k].length === 0) delete m[k];
      }
      if (m.skip_comment_prefix === '') delete m.skip_comment_prefix;
      if (m.min_columns === 0) delete m.min_columns;
      if (m.min_score === 0) delete m.min_score;
      out.match = m;
    }
    // Strip empty extract containers.
    if (out.extract) {
      const e = { ...out.extract };
      if (Array.isArray(e.fields) && e.fields.length === 0) delete e.fields;
      for (const k of ['columns', 'paths', 'keys']) {
        if (e[k] && Object.keys(e[k]).length === 0) delete e[k];
      }
      if (Object.keys(e).length === 0) delete out.extract;
      else out.extract = e;
    }
    return out;
  }

  async function onSave() {
    busy = true; saveMsg = null; error = null;
    try {
      if (isNew) await createRule(cleanRule);
      else await updateRule(slug, cleanRule);
      saveMsg = 'Saved.';
      if (isNew) goto(`/tuning/stealer/rules/${cleanRule.id}`);
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

  // ------- normalize step helpers -------
  function moveStep(i, dir) {
    const n = (rule.normalize ?? []).slice();
    const j = i + dir;
    if (j < 0 || j >= n.length) return;
    [n[i], n[j]] = [n[j], n[i]];
    rule.normalize = n;
  }
  function addStep() { rule.normalize = [...(rule.normalize ?? []), { verb: 'strip_whitespace', field: '' }]; }
  function removeStep(i) { rule.normalize = rule.normalize.filter((_, k) => k !== i); }
  function addReject() { rule.reject_patterns = [...(rule.reject_patterns ?? []), '']; }
  function removeReject(i) { rule.reject_patterns = rule.reject_patterns.filter((_, k) => k !== i); }

  // ------- string-list helpers (requires/forbids/optional/fields/requires_keys/requires_sections) -------
  function listGet(obj, key) { return Array.isArray(obj?.[key]) ? obj[key] : []; }
  function listAdd(obj, key) { obj[key] = [...listGet(obj, key), '']; }
  function listRemove(obj, key, i) { obj[key] = listGet(obj, key).filter((_, k) => k !== i); }
  function listSet(obj, key, i, v) { const a = listGet(obj, key).slice(); a[i] = v; obj[key] = a; }

  // ------- kv-map helpers (columns/paths/keys/rename) -------
  // Edits are tracked as an ordered array of {k, v} pairs so key edits don't
  // re-order / collide; serialised back to an object at read time.
  let mapRows = $state({}); // match/extract container key -> rows[]
  function ensureRows(container, mapKey) {
    const id = container + ':' + mapKey;
    if (mapRows[id]) return mapRows[id];
    const src = (container === 'match' ? rule.match : rule.extract)?.[mapKey] ?? {};
    const rows = Object.entries(src).map(([k, v]) => ({ k, v }));
    mapRows[id] = rows;
    return rows;
  }
  function syncMap(container, mapKey) {
    const id = container + ':' + mapKey;
    const obj = {};
    for (const r of mapRows[id] ?? []) if (r.k) obj[r.k] = r.v;
    if (container === 'match') rule.match[mapKey] = obj;
    else rule.extract[mapKey] = obj;
  }
  function addMapRow(container, mapKey) {
    const id = container + ':' + mapKey;
    mapRows[id] = [...(mapRows[id] ?? []), { k: '', v: '' }];
  }
  function removeMapRow(container, mapKey, i) {
    const id = container + ':' + mapKey;
    mapRows[id] = (mapRows[id] ?? []).filter((_, k) => k !== i);
    syncMap(container, mapKey);
  }
</script>

<div class="page">
  {#if loading}
    <div class="empty">Loading rule...</div>
  {:else if error && !rule.id}
    <div class="empty err">Load failed: <code>{error}</code></div>
  {:else}
    <!-- Sticky top bar spans full width -->
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

    <div class="cols">
      <!-- LEFT: form -->
      <div class="editor">
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

        <!-- 01 MATCH -->
        <section class="layer">
          <header>
            <span class="n">01</span>
            <span class="label">Match</span>
            <span class="hint">which bytes qualify as a hit</span>
          </header>
          <div class="pad">
            <label>
              <span>Match type</span>
              <select class="mono" bind:value={rule.match.type}>
                {#each MATCH_TYPES as t}<option value={t}>{t}</option>{/each}
              </select>
            </label>

            {#if rule.match.type === 'folder'}
              {#each ['requires', 'forbids', 'optional'] as key}
                <div class="field">
                  <div class="field-label">{key}</div>
                  {#each listGet(rule.match, key) as item, i}
                    <div class="row">
                      <input class="mono flex" type="text" value={item} oninput={(e) => listSet(rule.match, key, i, e.currentTarget.value)} placeholder={key === 'optional' ? 'file or dir/ pattern' : 'required path'} />
                      <button class="btn-ghost sm" onclick={() => listRemove(rule.match, key, i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => listAdd(rule.match, key)}>+ Add {key}</button>
                </div>
              {/each}
              <label>
                <span>Min score (requires + optional hits)</span>
                <input class="mono" type="number" bind:value={rule.match.min_score} />
              </label>

            {:else if rule.match.type === 'regex'}
              <label>
                <span>Pattern (RE2)</span>
                <textarea class="mono" rows="3" bind:value={rule.match.pattern} placeholder={'^HWID:\\s*(?P<hwid>[A-F0-9-]+)$'}></textarea>
              </label>
              <div class="cklist">
                <label class="ck"><input type="checkbox" bind:checked={rule.match.multiline} /> multiline (^ / $ match line bounds)</label>
                <label class="ck"><input type="checkbox" bind:checked={rule.match.dotall} /> dotall (. matches newline)</label>
              </div>

            {:else if rule.match.type === 'delimiter'}
              <div class="grid2">
                <label>
                  <span>Separator</span>
                  <input class="mono" type="text" bind:value={rule.match.separator} placeholder={'\\t'} />
                </label>
                <label>
                  <span>Min columns</span>
                  <input class="mono" type="number" bind:value={rule.match.min_columns} />
                </label>
                <label>
                  <span>Skip comment prefix (optional)</span>
                  <input class="mono" type="text" bind:value={rule.match.skip_comment_prefix} placeholder="#" />
                </label>
                <label class="ck mid"><input type="checkbox" bind:checked={rule.match.skip_blank} /> skip blank lines</label>
              </div>

            {:else if rule.match.type === 'template'}
              <label>
                <span>Template</span>
                <textarea class="mono" rows="4" bind:value={rule.match.template} placeholder={'URL: {url}\nUSER: {username}\nPASS: {password}'}></textarea>
              </label>
              <label class="ck"><input type="checkbox" bind:checked={rule.match.multiline} /> multiline anchors</label>

            {:else if rule.match.type === 'json' || rule.match.type === 'yaml'}
              <div class="field">
                <div class="field-label">requires_keys (top-level)</div>
                {#each listGet(rule.match, 'requires_keys') as item, i}
                  <div class="row">
                    <input class="mono flex" type="text" value={item} oninput={(e) => listSet(rule.match, 'requires_keys', i, e.currentTarget.value)} placeholder="HWID" />
                    <button class="btn-ghost sm" onclick={() => listRemove(rule.match, 'requires_keys', i)}>x</button>
                  </div>
                {/each}
                <button class="btn-ghost sm" onclick={() => listAdd(rule.match, 'requires_keys')}>+ Add key</button>
              </div>

            {:else if rule.match.type === 'keyvalue'}
              <div class="grid2">
                <label>
                  <span>Separator</span>
                  <input class="mono" type="text" bind:value={rule.match.separator} placeholder={': '} />
                </label>
                <label class="ck mid"><input type="checkbox" bind:checked={rule.match.strip_whitespace} /> strip whitespace from key / value</label>
              </div>
              <div class="field">
                <div class="field-label">requires_keys (case-insensitive)</div>
                {#each listGet(rule.match, 'requires_keys') as item, i}
                  <div class="row">
                    <input class="mono flex" type="text" value={item} oninput={(e) => listSet(rule.match, 'requires_keys', i, e.currentTarget.value)} placeholder="HWID" />
                    <button class="btn-ghost sm" onclick={() => listRemove(rule.match, 'requires_keys', i)}>x</button>
                  </div>
                {/each}
                <button class="btn-ghost sm" onclick={() => listAdd(rule.match, 'requires_keys')}>+ Add key</button>
              </div>

            {:else if rule.match.type === 'keyvalue_ini'}
              <div class="field">
                <div class="field-label">requires_sections</div>
                {#each listGet(rule.match, 'requires_sections') as item, i}
                  <div class="row">
                    <input class="mono flex" type="text" value={item} oninput={(e) => listSet(rule.match, 'requires_sections', i, e.currentTarget.value)} placeholder="Hardware" />
                    <button class="btn-ghost sm" onclick={() => listRemove(rule.match, 'requires_sections', i)}>x</button>
                  </div>
                {/each}
                <button class="btn-ghost sm" onclick={() => listAdd(rule.match, 'requires_sections')}>+ Add section</button>
              </div>
            {/if}
          </div>
        </section>

        <!-- 02 EXTRACT -->
        {#if rule.match.type !== 'folder'}
          <section class="layer">
            <header>
              <span class="n">02</span>
              <span class="label">Extract</span>
              <span class="hint">which fields to keep</span>
            </header>
            <div class="pad">
              {#if rule.match.type === 'regex' || rule.match.type === 'template'}
                <div class="field">
                  <div class="field-label">Fields (named captures to keep)</div>
                  {#each listGet(rule.extract, 'fields') as item, i}
                    <div class="row">
                      <input class="mono flex" type="text" value={item} oninput={(e) => listSet(rule.extract, 'fields', i, e.currentTarget.value)} placeholder="hwid" />
                      <button class="btn-ghost sm" onclick={() => listRemove(rule.extract, 'fields', i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => listAdd(rule.extract, 'fields')}>+ Add field</button>
                </div>

              {:else if rule.match.type === 'delimiter'}
                <div class="field">
                  <div class="field-label">Columns (index to field name)</div>
                  {#each ensureRows('extract', 'columns') as row, i}
                    <div class="kv">
                      <input class="mono num" type="number" bind:value={row.k} oninput={() => syncMap('extract', 'columns')} placeholder="0" />
                      <span class="arrow">to</span>
                      <input class="mono flex" type="text" bind:value={row.v} oninput={() => syncMap('extract', 'columns')} placeholder="host" />
                      <button class="btn-ghost sm" onclick={() => removeMapRow('extract', 'columns', i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => addMapRow('extract', 'columns')}>+ Add column</button>
                </div>

              {:else if rule.match.type === 'json' || rule.match.type === 'yaml'}
                <div class="field">
                  <div class="field-label">Paths (output field to JSONPath-lite)</div>
                  {#each ensureRows('extract', 'paths') as row, i}
                    <div class="kv">
                      <input class="mono flex" type="text" bind:value={row.k} oninput={() => syncMap('extract', 'paths')} placeholder="hwid" />
                      <span class="arrow">to</span>
                      <input class="mono flex" type="text" bind:value={row.v} oninput={() => syncMap('extract', 'paths')} placeholder="$.HWID" />
                      <button class="btn-ghost sm" onclick={() => removeMapRow('extract', 'paths', i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => addMapRow('extract', 'paths')}>+ Add path</button>
                </div>

              {:else if rule.match.type === 'keyvalue'}
                <div class="field">
                  <div class="field-label">Keys (source key to output field)</div>
                  {#each ensureRows('extract', 'keys') as row, i}
                    <div class="kv">
                      <input class="mono flex" type="text" bind:value={row.k} oninput={() => syncMap('extract', 'keys')} placeholder="HWID" />
                      <span class="arrow">to</span>
                      <input class="mono flex" type="text" bind:value={row.v} oninput={() => syncMap('extract', 'keys')} placeholder="hwid" />
                      <button class="btn-ghost sm" onclick={() => removeMapRow('extract', 'keys', i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => addMapRow('extract', 'keys')}>+ Add key</button>
                </div>

              {:else if rule.match.type === 'keyvalue_ini'}
                <div class="field">
                  <div class="field-label">Keys (Section.Key to output field)</div>
                  {#each ensureRows('extract', 'keys') as row, i}
                    <div class="kv">
                      <input class="mono flex" type="text" bind:value={row.k} oninput={() => syncMap('extract', 'keys')} placeholder="Hardware.HWID" />
                      <span class="arrow">to</span>
                      <input class="mono flex" type="text" bind:value={row.v} oninput={() => syncMap('extract', 'keys')} placeholder="hwid" />
                      <button class="btn-ghost sm" onclick={() => removeMapRow('extract', 'keys', i)}>x</button>
                    </div>
                  {/each}
                  <button class="btn-ghost sm" onclick={() => addMapRow('extract', 'keys')}>+ Add key</button>
                </div>
              {/if}

              <div class="field">
                <div class="field-label">Reject patterns (RE2, drops the whole match on any hit)</div>
                {#each rule.reject_patterns as pat, i}
                  <div class="row">
                    <input class="mono flex" type="text" value={pat} oninput={(e) => (rule.reject_patterns[i] = e.currentTarget.value)} placeholder="(?i)\bbanner\b" />
                    <button class="btn-ghost sm" onclick={() => removeReject(i)}>x</button>
                  </div>
                {/each}
                <button class="btn-ghost sm" onclick={addReject}>+ Add reject pattern</button>
              </div>
            </div>
          </section>
        {/if}

        <!-- 03 NORMALIZE -->
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
                      {#each DATE_FORMATS as f}<option value={f}>{f}</option>{/each}
                    </select>
                  {/if}
                  <div class="row-actions">
                    <button class="btn-ghost sm" onclick={() => moveStep(i, -1)} disabled={i === 0} title="Move up">^</button>
                    <button class="btn-ghost sm" onclick={() => moveStep(i, 1)} disabled={i === (rule.normalize?.length ?? 0) - 1} title="Move down">v</button>
                    <button class="btn-ghost sm" onclick={() => removeStep(i)}>x</button>
                  </div>
                </div>
              {/each}
              <button class="btn-ghost sm add" onclick={addStep}>+ Add normalize step</button>
            </div>
          </div>
        </section>
      </div>

      <!-- RIGHT: sticky live JSON preview -->
      <aside class="jsonpanel">
        <header>
          <span class="n">.</span>
          <span class="label">Rule JSON</span>
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
  .topbar .back {
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase; color: var(--text-muted); text-decoration: none;
  }
  .topbar .back:hover { color: var(--accent-text); }
  .topbar h2 { margin: 0; font-family: var(--font-sans); font-size: var(--fs-16); font-weight: var(--fw-semibold); color: var(--text); }
  .topbar h2 .mono { font-family: var(--font-mono); color: var(--accent-text); }
  .topbar .spacer { flex: 1; }
  .topbar .saved { color: var(--accent-text); font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; }
  .topbar .errbar { color: var(--red-text); font-family: var(--font-mono); font-size: var(--fs-11); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

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
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

  label { display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  label > span { text-transform: uppercase; letter-spacing: var(--tracking-label); font-size: var(--fs-11); color: var(--text-faint); font-weight: var(--fw-semibold); }
  input[type="text"], input[type="number"], select, textarea {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 6px 10px; color: var(--text);
    font-family: var(--font-sans); font-size: var(--fs-13);
    outline: none; min-width: 0;
  }
  input.mono, select.mono, textarea.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  input.num { max-width: 90px; }
  input.flex { flex: 1; }
  input:focus, select:focus, textarea:focus { border-color: var(--accent); }
  input:disabled, select:disabled { opacity: .5; cursor: not-allowed; }

  textarea { resize: vertical; min-height: 80px; }

  .pad { padding: 14px; display: flex; flex-direction: column; gap: 14px; }

  .field { display: flex; flex-direction: column; gap: 6px; }
  .field-label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); color: var(--text-faint); text-transform: uppercase; letter-spacing: var(--tracking-label); }
  .row { display: flex; gap: 6px; align-items: center; }

  .kv { display: grid; grid-template-columns: minmax(80px, 1fr) auto minmax(80px, 1fr) auto; gap: 6px; align-items: center; }
  .kv .arrow { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); text-transform: uppercase; }

  .cklist { display: flex; flex-direction: column; gap: 6px; }
  .ck { display: flex; flex-direction: row; align-items: center; gap: 6px; color: var(--text); text-transform: none; letter-spacing: normal; font-size: var(--fs-12); }
  .ck.mid { align-self: end; padding-bottom: 6px; }

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
