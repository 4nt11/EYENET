<script>
  import Badge from './Badge.svelte';
  // Dense evidence table. columns: [{ key, header, width?, align?, mono?, badge? }]
  //
  // Opt-in layout flags (all default off, so existing callers are untouched):
  //   stickyHead  — the <thead> row sticks while an ANCESTOR scroll container
  //                 scrolls. Requires the table's own wrapper to NOT be a scroll
  //                 container, so it also drops the wrap's clipping overflow.
  //   stickyTop   — offset for the sticky header (e.g. under a sticky section bar).
  //   flat        — drop the wrap border/radius (when the table sits inside an
  //                 already-framed section).
  //   fixed       — table-layout:fixed + per-cell ellipsis, so long text truncates
  //                 instead of forcing horizontal overflow (needed when stickyHead
  //                 removes the wrap's horizontal clip).
  let {
    columns = [],
    rows = [],
    onRowClick,
    selectedId = null,
    rowKey = 'id',
    stickyHead = false,
    stickyTop = '0',
    flat = false,
    fixed = false
  } = $props();
</script>

<div class="wrap" class:sticky={stickyHead} class:flat class:fixed>
  <table>
    <thead>
      <tr>
        {#each columns as c}
          <th style="text-align:{c.align ?? 'left'}; width:{c.width ?? 'auto'}; top:{stickyTop};">{c.header}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as r, i}
        {@const id = r[rowKey] ?? i}
        {@const sel = selectedId != null && id === selectedId}
        <tr
          class:sel
          class:clickable={!!onRowClick}
          onclick={onRowClick ? () => onRowClick(r) : undefined}
        >
          {#each columns as c}
            <td
              class:mono={c.mono}
              style="text-align:{c.align ?? 'left'};"
            >
              {#if c.badge}
                <Badge tone={c.tone ? c.tone(r[c.key], r) : r[c.key]}>{r[c.key]}</Badge>
              {:else}
                {r[c.key]}
              {/if}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .wrap {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    background: var(--surface);
  }
  /* Sticky-head mode: the wrapper must not clip or create a scroll context, so
     the <thead> can stick to the nearest *ancestor* scroll container (the page). */
  .wrap.sticky { overflow: visible; }
  .wrap.flat { border: none; border-radius: 0; background: transparent; }
  table { width: 100%; border-collapse: collapse; font-family: var(--font-sans); }
  .wrap.fixed table { table-layout: fixed; }
  .wrap.sticky th { position: sticky; z-index: 1; }
  .wrap.fixed td, .wrap.fixed th { overflow: hidden; text-overflow: ellipsis; }
  th {
    padding: 8px 12px;
    font-size: var(--fs-11);
    font-weight: var(--fw-semibold);
    letter-spacing: var(--tracking-label);
    text-transform: uppercase;
    color: var(--text-faint);
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  td {
    padding: 7px 12px;
    font-size: var(--fs-13);
    color: var(--text-body);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    vertical-align: middle;
    border-left: 2px solid transparent;
  }
  td.mono {
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
  }
  tr.clickable { cursor: pointer; }
  tr.clickable:hover td { background: var(--panel); }
  tr.sel td { background: var(--accent-fill); }
  tr.sel td:first-child { border-left-color: var(--accent-text); }
</style>
