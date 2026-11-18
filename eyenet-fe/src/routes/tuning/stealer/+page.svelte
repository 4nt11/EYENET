<script>
  import { onMount } from 'svelte';
  import { listRules } from '$lib/stealerRulesApi.svelte.js';

  let rules = $state([]);
  let loading = $state(true);
  let error = $state(null);
  let query = $state('');

  onMount(async () => {
    try {
      rules = await listRules();
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      loading = false;
    }
  });

  const match = (r) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      r.id.toLowerCase().includes(q) ||
      r.family.toLowerCase().includes(q) ||
      (r.path_glob ?? '').toLowerCase().includes(q) ||
      (r.match?.type ?? '').toLowerCase().includes(q)
    );
  };

  const container = $derived(
    rules.filter((r) => r.layer === 'container' && match(r)).sort((a, b) => b.priority - a.priority)
  );
  const content = $derived(
    rules.filter((r) => r.layer === 'content' && match(r)).sort((a, b) => b.priority - a.priority)
  );

  // L2: derived set of unique path_globs across content rules. The DSL does
  // not model file handlers explicitly; this view surfaces the implicit
  // routing table so an operator can SEE which file shapes get what parser.
  const handlers = $derived(() => {
    const groups = new Map();
    for (const r of content) {
      const g = r.path_glob ?? '**/*';
      const entry = groups.get(g) ?? { path_glob: g, types: new Set(), rules: [], families: new Set() };
      entry.types.add(r.match?.type);
      entry.families.add(r.family);
      entry.rules.push(r.id);
      groups.set(g, entry);
    }
    return [...groups.values()].sort((a, b) => a.path_glob.localeCompare(b.path_glob));
  });

  const counts = $derived({
    total: rules.length,
    container: rules.filter((r) => r.layer === 'container').length,
    content: rules.filter((r) => r.layer === 'content').length,
    families: new Set(rules.map((r) => r.family)).size
  });
</script>

<div class="wrap">
  <div class="toolbar">
    <div class="stats">
      <span class="stat"><em>{counts.total}</em> rules</span>
      <span class="sep"></span>
      <span class="stat"><em>{counts.container}</em> container</span>
      <span class="sep"></span>
      <span class="stat"><em>{counts.content}</em> content</span>
      <span class="sep"></span>
      <span class="stat"><em>{counts.families}</em> families</span>
    </div>
    <input
      type="search"
      bind:value={query}
      placeholder="Filter by id, family, path glob, or type"
      aria-label="Filter rules"
    />
    <a class="btn-primary" href="/tuning/stealer/rules/new">+ New rule</a>
  </div>

  {#if loading}
    <div class="empty">Loading catalog...</div>
  {:else if error}
    <div class="empty err">Catalog load failed: <code>{error}</code></div>
  {:else}
    <section class="layer">
      <header>
        <span class="n">01</span>
        <span class="label">L1 Container rules</span>
        <span class="hint">which stealer, which log</span>
        <span class="count">{container.length}</span>
      </header>
      <table>
        <thead>
          <tr>
            <th class="pri">Pri</th>
            <th>Id</th>
            <th>Family</th>
            <th>Match</th>
            <th>Requires</th>
            <th class="en">On</th>
          </tr>
        </thead>
        <tbody>
          {#each container as r (r.id)}
            <tr onclick={() => (window.location.href = `/tuning/stealer/rules/${r.id}`)} role="button" tabindex="0">
              <td class="pri mono">{r.priority}</td>
              <td class="mono id">{r.id}</td>
              <td><span class="family">{r.family}</span></td>
              <td class="mono muted">{r.match?.type ?? ''}</td>
              <td class="mono muted">{(r.match?.requires ?? []).join(', ') || '*'}</td>
              <td class="en"><span class="dot on" title="enabled"></span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>

    <section class="layer">
      <header>
        <span class="n">02</span>
        <span class="label">L2 File handlers</span>
        <span class="hint">derived · which parser per file shape</span>
        <span class="count">{handlers().length}</span>
      </header>
      <table>
        <thead>
          <tr>
            <th>Path glob</th>
            <th>Parser types</th>
            <th>Families</th>
            <th>Rules</th>
          </tr>
        </thead>
        <tbody>
          {#each handlers() as h (h.path_glob)}
            <tr>
              <td class="mono id">{h.path_glob}</td>
              <td class="mono muted">{[...h.types].join(', ')}</td>
              <td class="mono muted">{[...h.families].join(', ')}</td>
              <td class="mono muted">{h.rules.length}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>

    <section class="layer">
      <header>
        <span class="n">03</span>
        <span class="label">L3 Content rules</span>
        <span class="hint">fields per record</span>
        <span class="count">{content.length}</span>
      </header>
      <table>
        <thead>
          <tr>
            <th class="pri">Pri</th>
            <th>Id</th>
            <th>Family</th>
            <th>Type</th>
            <th>Path glob</th>
            <th>Fields</th>
            <th class="en">On</th>
          </tr>
        </thead>
        <tbody>
          {#each content as r (r.id)}
            <tr onclick={() => (window.location.href = `/tuning/stealer/rules/${r.id}`)} role="button" tabindex="0">
              <td class="pri mono">{r.priority}</td>
              <td class="mono id">{r.id}</td>
              <td><span class="family">{r.family}</span></td>
              <td class="mono muted">{r.match?.type}</td>
              <td class="mono muted">{r.path_glob ?? '**/*'}</td>
              <td class="mono muted">{fieldCount(r)}</td>
              <td class="en"><span class="dot on" title="enabled"></span></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}
</div>

<script module>
  // Count of extraction field names declared on a content rule.
  export function fieldCount(r) {
    const ex = r.extract;
    if (!ex) return 0;
    if (ex.fields) return ex.fields.length;
    if (ex.columns) return Object.keys(ex.columns).length;
    if (ex.paths) return Object.keys(ex.paths).length;
    if (ex.keys) return Object.keys(ex.keys).length;
    return 0;
  }
</script>

<style>
  .wrap { display: flex; flex-direction: column; gap: 20px; }

  .toolbar {
    display: flex; align-items: center; gap: 16px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
  }
  .stats { display: flex; align-items: center; gap: 10px; flex: 1; }
  .stat {
    font-family: var(--font-mono); font-size: var(--fs-11);
    letter-spacing: var(--tracking-label); text-transform: uppercase;
    color: var(--text-faint);
  }
  .stat em { font-style: normal; color: var(--text); font-weight: var(--fw-semibold); }
  .sep { width: 1px; height: 14px; background: var(--border); }
  input[type="search"] {
    flex: 0 0 320px; max-width: 320px;
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 6px 10px;
    color: var(--text); font-family: var(--font-sans); font-size: var(--fs-13);
    outline: none;
  }
  input[type="search"]:focus { border-color: var(--accent); }
  .btn-primary {
    background: var(--accent); color: white; border: 1px solid var(--accent);
    border-radius: var(--radius); padding: 6px 12px;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    cursor: pointer; transition: background 120ms ease; text-decoration: none;
    display: inline-flex; align-items: center;
  }
  .btn-primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
  .btn-primary:disabled { opacity: .45; cursor: not-allowed; }

  .empty {
    padding: 40px; text-align: center; color: var(--text-muted);
    font-family: var(--font-mono); font-size: var(--fs-13);
    border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel);
  }
  .empty.err { color: var(--red-text); border-color: var(--red-fill-strong); }
  .empty code { color: var(--text); background: var(--surface); padding: 1px 6px; border-radius: var(--radius-sm); }

  .layer { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  .layer > header {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px;
    background: var(--panel-2); border-bottom: 1px solid var(--border);
  }
  .layer > header .n {
    font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint);
    letter-spacing: var(--tracking-label);
  }
  .layer > header .label {
    font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold);
    color: var(--text);
  }
  .layer > header .hint {
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data);
    color: var(--text-muted); flex: 1;
  }
  .layer > header .count {
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    color: var(--accent-text); text-transform: uppercase;
  }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left; padding: 8px 14px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label); text-transform: uppercase;
    color: var(--text-faint);
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  th.pri, th.en, td.pri, td.en { width: 40px; text-align: center; }
  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background 120ms ease;
  }
  tbody tr:last-child { border-bottom: none; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--panel-2); }
  tbody td {
    padding: 7px 14px;
    font-family: var(--font-sans); font-size: var(--fs-13); color: var(--text);
    vertical-align: middle;
  }
  td.mono { font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data); }
  td.muted { color: var(--text-muted); }
  td.id { color: var(--accent-text); }

  .family {
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    padding: 2px 6px; border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text-muted); background: var(--surface);
  }

  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
  .dot.on { background: var(--accent-text); }
</style>
