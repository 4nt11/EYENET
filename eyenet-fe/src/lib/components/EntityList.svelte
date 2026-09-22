<script>
  import Badge from './Badge.svelte';
  // Selectable left rail of entities (actors, personas). Row = primary + secondary + tier dot.
  // items: [{ id, primary, secondary, tier }]
  let { label, items = [], selectedId, onSelect } = $props();
</script>

<aside>
  <div class="head">
    <span class="label">{label}</span>
    <span class="count">{items.length}</span>
  </div>
  <div class="list">
    {#each items as it (it.id)}
      <button class="row" class:active={it.id === selectedId} onclick={() => onSelect(it.id)}>
        <span class="rail" style="background:{it.tier === 'critical' ? 'var(--red)' : it.tier === 'high' ? 'var(--accent)' : 'var(--border-strong)'};"></span>
        <span class="text">
          <span class="primary">{it.primary}</span>
          <span class="secondary">{it.secondary}</span>
        </span>
        <Badge tone={it.tier} dot>{it.tier}</Badge>
      </button>
    {/each}
  </div>
</aside>

<style>
  aside { width: 300px; flex: 0 0 auto; display: flex; flex-direction: column; background: var(--black); border-right: 1px solid var(--border); overflow: hidden; }
  .head { padding: 10px 14px; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
  .label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .list { overflow: auto; padding: 8px; display: flex; flex-direction: column; gap: 4px; }

  .row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px 8px 0;
    border: 1px solid transparent;
    border-radius: var(--radius);
    background: transparent;
    cursor: pointer;
    text-align: left;
    transition: background 120ms ease, border-color 120ms ease;
  }
  .row:hover { background: var(--panel); }
  .row.active { background: var(--accent-fill); border-color: var(--accent); }
  .rail { width: 3px; align-self: stretch; border-radius: 2px; flex: 0 0 auto; }
  .text { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
  .primary { font-family: var(--font-mono); font-size: var(--fs-13); letter-spacing: var(--tracking-data); color: var(--text-body); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .secondary { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
</style>
