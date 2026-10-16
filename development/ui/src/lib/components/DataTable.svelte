<script>
  import Badge from './Badge.svelte';
  // Dense evidence table. columns: [{ key, header, width?, align?, mono?, badge? }]
  let { columns = [], rows = [], onRowClick, selectedId = null, rowKey = 'id' } = $props();
</script>

<div class="wrap">
  <table>
    <thead>
      <tr>
        {#each columns as c}
          <th style="text-align:{c.align ?? 'left'}; width:{c.width ?? 'auto'};">{c.header}</th>
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
  table { width: 100%; border-collapse: collapse; font-family: var(--font-sans); }
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
