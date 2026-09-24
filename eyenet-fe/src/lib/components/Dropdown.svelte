<script>
  // Styled select replacement: a native <select>'s option popup is OS-drawn and
  // unstyleable, so this renders its own dark menu. options: [{ v, l }].
  let { options = [], value = $bindable(), onchange = null, minWidth = '150px' } = $props();
  let open = $state(false);
  let root;
  const selected = $derived(options.find((o) => o.v === value) ?? options[0]);

  function pick(o) { value = o.v; open = false; onchange?.(); }
  function onDoc(e) { if (root && !root.contains(e.target)) open = false; }
  $effect(() => {
    if (!open) return;
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  });
</script>

<div class="dd" bind:this={root} style="min-width:{minWidth}">
  <button type="button" class="ddbtn" class:open onclick={() => (open = !open)}>
    <span class="ddlabel">{selected?.l ?? ''}</span>
    <span class="ddcaret">▾</span>
  </button>
  {#if open}
    <div class="ddmenu">
      {#each options as o}
        <button type="button" class="dditem" class:on={o.v === value} onclick={() => pick(o)}>{o.l}</button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dd { position: relative; }
  .ddbtn { width: 100%; height: 28px; display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); padding: 0 8px; cursor: pointer; }
  .ddbtn:hover { border-color: var(--accent); }
  .ddbtn.open { border-color: var(--accent); }
  .ddlabel { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ddcaret { color: var(--accent-text); font-size: 10px; flex: 0 0 auto; }

  .ddmenu { position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 40; display: flex; flex-direction: column; padding: 4px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); max-height: 280px; overflow: auto; }
  .dditem { text-align: left; background: transparent; border: none; border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 8px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .dditem:hover { background: var(--panel-2); }
  .dditem.on { background: var(--accent-fill); color: var(--text); }
</style>
