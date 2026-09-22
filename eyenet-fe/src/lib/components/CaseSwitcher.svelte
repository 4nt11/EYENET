<script>
  import { Popover } from 'bits-ui';
  import { goto } from '$app/navigation';
  
  import { caseCtx, enterCase, exitCase } from '$lib/case.svelte.js';

  let open = $state(false);
  const tierDot = (t) => (t === 'classified' ? 'var(--red)' : t === 'restricted' ? 'var(--accent)' : 'var(--border-strong)');

  function pick(id) {
    enterCase(id);
    open = false;
    goto('/cases');
  }
  function leave() {
    exitCase();
    open = false;
    goto('/cases');
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger class="cs-trigger">
    {#if caseCtx.active}
      <span class="cs-mode">CASE</span>
      <span class="cs-dot" style="background:{tierDot(caseCtx.active.tier)}"></span>
      <span class="cs-id">{caseCtx.active.caseId}</span>
    {:else}
      <span class="cs-none">Select case</span>
    {/if}
    <svg class="cs-chev" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 9l6 6 6-6" /></svg>
  </Popover.Trigger>
  <Popover.Portal>
    <Popover.Content class="cs-content" sideOffset={6} align="start">
      <div class="cs-head">Enter a case</div>
      {#each caseCtx.list as c}
        <button class="cs-item" class:sel={caseCtx.active?.caseId === c.caseId} onclick={() => pick(c.caseId)}>
          <span class="cs-dot" style="background:{tierDot(c.tier)}"></span>
          <span class="cs-item-id">{c.caseId}</span>
          <span class="cs-item-title">{c.title}</span>
        </button>
      {/each}
      {#if caseCtx.active}
        <div class="cs-sep"></div>
        <button class="cs-exit" onclick={leave}>Exit case mode</button>
      {/if}
    </Popover.Content>
  </Popover.Portal>
</Popover.Root>

<style>
  :global(.cs-trigger) {
    display: inline-flex; align-items: center; gap: 7px;
    height: 26px; padding: 0 10px;
    border: 1px solid var(--border-strong); border-radius: var(--radius);
    background: var(--panel); cursor: pointer;
    font-family: var(--font-mono); font-size: var(--fs-12); letter-spacing: var(--tracking-data);
    color: var(--text-body);
  }
  :global(.cs-trigger:hover) { background: var(--panel-2); }
  :global(.cs-trigger[data-state="open"]) { border-color: var(--accent); }
  .cs-mode { font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); color: var(--accent-text); }
  .cs-dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
  .cs-id { color: var(--text); }
  .cs-none { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-muted); }
  .cs-chev { color: var(--text-faint); }

  :global(.cs-content) {
    width: 320px; z-index: 70;
    border: 1px solid var(--border-strong); border-radius: var(--radius);
    background: var(--panel-2); padding: 6px;
    display: flex; flex-direction: column; gap: 1px;
  }
  :global(.cs-content) .cs-head { padding: 6px 10px 4px; font-family: var(--font-sans); font-size: var(--fs-11); font-weight: var(--fw-semibold); letter-spacing: var(--tracking-label); text-transform: uppercase; color: var(--text-faint); }
  :global(.cs-content) .cs-item { display: grid; grid-template-columns: 8px 96px 1fr; gap: 8px; align-items: center; padding: 7px 10px; border: none; border-radius: var(--radius); background: transparent; cursor: pointer; text-align: left; }
  :global(.cs-content) .cs-item:hover { background: var(--panel); }
  :global(.cs-content) .cs-item.sel { background: var(--accent-fill); }
  :global(.cs-content) .cs-item-id { font-family: var(--font-mono); font-size: var(--fs-11); letter-spacing: var(--tracking-data); color: var(--accent-text); }
  :global(.cs-content) .cs-item-title { font-family: var(--font-sans); font-size: var(--fs-12); color: var(--text-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  :global(.cs-content) .cs-sep { height: 1px; background: var(--border); margin: 4px 0; }
  :global(.cs-content) .cs-exit { padding: 7px 10px; border: none; border-radius: var(--radius); background: transparent; cursor: pointer; text-align: left; font-family: var(--font-sans); font-size: var(--fs-12); color: var(--red-text); }
  :global(.cs-content) .cs-exit:hover { background: var(--red-fill); }
</style>
