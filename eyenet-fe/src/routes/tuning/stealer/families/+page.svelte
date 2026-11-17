<script>
  import { onMount } from 'svelte';

  let families = $state([]);
  let rules = $state([]);
  let loading = $state(true);
  let error = $state(null);
  let query = $state('');
  let statusFilter = $state('all');

  onMount(async () => {
    try {
      const [fr, rr] = await Promise.all([
        fetch('/stealer-families.json'),
        fetch('/stealer-rules.json')
      ]);
      if (!fr.ok) throw new Error(`families fetch failed: ${fr.status}`);
      if (!rr.ok) throw new Error(`rules fetch failed: ${rr.status}`);
      families = await fr.json();
      rules = await rr.json();
    } catch (e) {
      error = String(e?.message ?? e);
    } finally {
      loading = false;
    }
  });

  const ruleCoverage = $derived(() => {
    const m = new Map();
    for (const r of rules) m.set(r.family, (m.get(r.family) ?? 0) + 1);
    return m;
  });

  const match = (f) => {
    if (statusFilter !== 'all' && f.status !== statusFilter) return false;
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      f.slug.toLowerCase().includes(q) ||
      f.name.toLowerCase().includes(q) ||
      (f.aliases ?? []).some((a) => a.toLowerCase().includes(q)) ||
      (f.loaders ?? []).some((a) => a.toLowerCase().includes(q)) ||
      (f.signature_files ?? []).some((a) => a.toLowerCase().includes(q))
    );
  };

  const filtered = $derived(families.filter(match).sort((a, b) => a.name.localeCompare(b.name)));

  const counts = $derived({
    total: families.length,
    active: families.filter((f) => f.status === 'active').length,
    dormant: families.filter((f) => f.status === 'dormant').length,
    retired: families.filter((f) => f.status === 'retired').length,
    new: families.filter((f) => f.status === 'new').length
  });

  const STATUS_FILTERS = ['all', 'active', 'new', 'dormant', 'retired', 'suspected'];
</script>

<div class="wrap">
  <div class="toolbar">
    <div class="stats">
      <span class="stat"><em>{counts.total}</em> families</span>
      <span class="sep"></span>
      <span class="stat act"><em>{counts.active}</em> active</span>
      <span class="sep"></span>
      <span class="stat new"><em>{counts.new}</em> new</span>
      <span class="sep"></span>
      <span class="stat"><em>{counts.dormant}</em> dormant</span>
      <span class="sep"></span>
      <span class="stat"><em>{counts.retired}</em> retired</span>
    </div>
    <input
      type="search"
      bind:value={query}
      placeholder="Filter by slug, name, alias, loader, signature file"
      aria-label="Filter families"
    />
    <a class="btn-primary" href="/tuning/stealer/families/new">+ New family</a>
  </div>

  <nav class="status-tabs">
    {#each STATUS_FILTERS as s}
      <button class="chip" class:active={statusFilter === s} onclick={() => (statusFilter = s)}>{s}</button>
    {/each}
  </nav>

  {#if loading}
    <div class="empty">Loading catalog...</div>
  {:else if error}
    <div class="empty err">Catalog load failed: <code>{error}</code></div>
  {:else}
    <section class="layer">
      <header>
        <span class="n">00</span>
        <span class="label">Family catalog</span>
        <span class="hint">operator-curated; drives the system family enum</span>
        <span class="count">{filtered.length}</span>
      </header>
      <table>
        <thead>
          <tr>
            <th>Slug</th>
            <th>Name</th>
            <th class="status-th">Status</th>
            <th>Aliases</th>
            <th>Loaders</th>
            <th>Sig files</th>
            <th>Refs</th>
            <th>Rules</th>
          </tr>
        </thead>
        <tbody>
          {#each filtered as f (f.slug)}
            <tr onclick={() => (window.location.href = `/tuning/stealer/families/${f.slug}`)} role="button" tabindex="0">
              <td class="mono id">{f.slug}</td>
              <td>{f.name}</td>
              <td class="status-td"><span class="status s-{f.status}">{f.status}</span></td>
              <td class="mono muted">{(f.aliases ?? []).join(', ') || '.'}</td>
              <td class="mono muted">{(f.loaders ?? []).slice(0, 3).join(', ')}{(f.loaders ?? []).length > 3 ? ` +${f.loaders.length - 3}` : ''}</td>
              <td class="mono muted n">{(f.signature_files ?? []).length}</td>
              <td class="mono muted n">{(f.references ?? []).length}</td>
              <td class="mono muted n">
                {#if ruleCoverage().get(f.slug)}
                  <span class="cov">{ruleCoverage().get(f.slug)}</span>
                {:else}
                  <span class="cov none" title="no rules reference this family yet">0</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; gap: 16px; }

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
  .stat.act em { color: var(--accent-text); }
  .stat.new em { color: var(--accent-text); }
  .sep { width: 1px; height: 14px; background: var(--border); }
  input[type="search"] {
    flex: 0 0 360px; max-width: 360px;
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
    cursor: pointer; transition: background 120ms ease;
  }
  .btn-primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
  .btn-primary:disabled { opacity: .45; cursor: not-allowed; }
  .btn-primary { text-decoration: none; display: inline-flex; align-items: center; }

  .status-tabs { display: flex; gap: 2px; }
  .chip {
    padding: 4px 10px;
    background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm);
    color: var(--text-muted);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase; cursor: pointer;
    transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
  }
  .chip:hover { background: var(--panel-2); color: var(--text); }
  .chip.active { background: var(--accent-fill); border-color: var(--accent); color: var(--accent-text); }

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
  .layer > header .n { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); letter-spacing: var(--tracking-label); }
  .layer > header .label { font-family: var(--font-sans); font-size: var(--fs-13); font-weight: var(--fw-semibold); color: var(--text); }
  .layer > header .hint { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-muted); flex: 1; }
  .layer > header .count { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label); color: var(--accent-text); text-transform: uppercase; }

  table { width: 100%; border-collapse: collapse; }
  thead th {
    text-align: left; padding: 8px 14px;
    font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label); text-transform: uppercase;
    color: var(--text-faint);
    border-bottom: 1px solid var(--border); background: var(--panel);
  }
  th.status-th, td.status-td { width: 90px; }
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
  td.n { text-align: right; width: 60px; }

  .status {
    display: inline-block;
    padding: 2px 8px;
    border: 1px solid var(--border); border-radius: var(--radius-sm);
    font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--text-muted); background: var(--surface);
  }
  .status.s-active   { color: var(--accent-text); border-color: var(--accent); background: var(--accent-fill); }
  .status.s-new      { color: var(--accent-text); border-color: var(--accent-text); background: var(--accent-fill); }
  .status.s-dormant  { color: var(--text-muted); }
  .status.s-retired  { color: var(--text-faint); border-color: var(--border); }
  .status.s-suspected { color: var(--red-text); border-color: var(--red-fill-strong); background: var(--red-fill); }

  .cov {
    display: inline-block; min-width: 20px; text-align: right;
    font-family: var(--font-mono); font-size: var(--fs-12);
    color: var(--accent-text);
  }
  .cov.none { color: var(--text-faint); }
</style>
