<script>
  import TierBadge from './TierBadge.svelte';
  let { caseId, title, tier = 'normal', actor, updated, openCount, active = false, onclick } = $props();
</script>

<div class="card" class:active {onclick} role={onclick ? 'button' : undefined} tabindex={onclick ? 0 : undefined}>
  <div class="top">
    <span class="cid">{caseId}</span>
    <TierBadge {tier} />
  </div>
  <div class="title">{title}</div>
  <div class="meta">
    {#if actor}<span class="m"><span class="ml">Actor</span><span class="mv mono">{actor}</span></span>{/if}
    {#if openCount != null}<span class="m"><span class="ml">Open leads</span><span class="mv">{openCount}</span></span>{/if}
    {#if updated}<span class="m"><span class="ml">Updated</span><span class="mv mono">{updated}</span></span>{/if}
  </div>
</div>

<style>
  .card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease;
  }
  .card:hover { background: var(--panel-2); }
  .card.active { border-color: var(--accent); background: var(--accent-fill); }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .cid { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--text-faint); }
  .title { font-family: var(--font-sans); font-size: var(--fs-14); font-weight: var(--fw-semibold); color: var(--text-body); line-height: var(--lh-tight); }
  .meta { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .m { display: inline-flex; flex-direction: column; gap: 2px; }
  .ml { font-family: var(--font-sans); font-size: var(--fs-11); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .mv { font-size: var(--fs-12); color: var(--text-secondary); }
  .mv.mono { font-family: var(--font-mono); letter-spacing: var(--tracking-data); }
</style>
