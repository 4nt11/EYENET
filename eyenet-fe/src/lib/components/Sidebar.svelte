<script>
  import CaseCard from './CaseCard.svelte';
  import { caseCtx } from '$lib/case.svelte.js';
  let { selected, onSelect } = $props();
</script>

<aside>
  <div class="head">
    <span class="label">Caseload</span>
    <span class="count">{caseCtx.list.length} active</span>
  </div>
  <div class="list">
    {#each caseCtx.list as c (c.caseId)}
      <CaseCard {...c} active={c.caseId === selected} onclick={() => onSelect(c.caseId)} />
    {:else}
      <span class="empty">{caseCtx.error ?? (caseCtx.loaded ? 'No cases' : 'Loading...')}</span>
    {/each}
  </div>
</aside>

<style>
  aside {
    width: 320px;
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    background: var(--black);
    border-right: 1px solid var(--border);
    overflow: hidden;
  }
  .head {
    padding: 10px 14px;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
  }
  .label { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  .count { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--text-faint); }
  .list { overflow: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .empty { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--text-faint); padding: 8px 2px; }
</style>
