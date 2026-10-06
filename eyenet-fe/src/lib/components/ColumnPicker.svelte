<script>
  // Checkbox menu for the Discover-style configurable columns. Modeled on
  // Dropdown.svelte's dark popup, but multi-select: each item toggles a key in
  // `selected`. `options` is [{ v, l, fixed? }] — a `fixed` option can't be
  // unchecked (e.g. Title, so a row is never blank). `selected` is a bindable
  // array of chosen keys; the parent persists it to localStorage.
  let { options = [], selected = $bindable([]), onchange = null, label = 'Columns' } = $props();
  let open = $state(false);
  let root;

  function toggle(o) {
    if (o.fixed) return;
    selected = selected.includes(o.v) ? selected.filter((k) => k !== o.v) : [...selected, o.v];
    onchange?.();
  }
  function onDoc(e) { if (root && !root.contains(e.target)) open = false; }
  $effect(() => {
    if (!open) return;
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  });
</script>

<div class="dd" bind:this={root}>
  <button type="button" class="ddbtn" class:open onclick={() => (open = !open)} aria-expanded={open}>
    <span class="ddlabel">{label}</span>
    <span class="ddn">{selected.length}</span>
    <span class="ddcaret">▾</span>
  </button>
  {#if open}
    <div class="ddmenu" role="menu">
      {#each options as o}
        <button
          type="button"
          class="dditem"
          class:on={selected.includes(o.v)}
          class:fixed={o.fixed}
          role="menuitemcheckbox"
          aria-checked={selected.includes(o.v)}
          onclick={() => toggle(o)}
        >
          <span class="box" aria-hidden="true">{selected.includes(o.v) ? '✓' : ''}</span>
          <span class="txt">{o.l}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dd { position: relative; }
  .ddbtn { height: 28px; display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-12); padding: 0 8px; cursor: pointer; }
  .ddbtn:hover, .ddbtn.open { border-color: var(--accent); }
  .ddn { font-family: var(--font-mono); font-size: var(--fs-11); color: var(--accent-text); }
  .ddcaret { color: var(--accent-text); font-size: 10px; }

  .ddmenu { position: absolute; top: calc(100% + 4px); right: 0; z-index: 40; display: flex; flex-direction: column; padding: 4px; min-width: 200px; background: var(--panel); border: 1px solid var(--border-strong); border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); max-height: 320px; overflow: auto; }
  .dditem { display: flex; align-items: center; gap: 8px; text-align: left; background: transparent; border: none; border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); padding: 6px 8px; cursor: pointer; white-space: nowrap; }
  .dditem:hover { background: var(--panel-2); }
  .dditem.fixed { opacity: .6; cursor: default; }
  .dditem .box { width: 14px; height: 14px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 10px; color: var(--accent-text); }
  .dditem.on .box { border-color: var(--accent); background: var(--accent-fill); }
  .txt { overflow: hidden; text-overflow: ellipsis; }
</style>
