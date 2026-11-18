<script>
  // Styled select replacement: a native <select>'s option popup is OS-drawn and
  // unstyleable, so this renders its own dark menu. options: [{ v, l }].
  //
  // The menu uses position: fixed so it escapes every ancestor's
  // overflow: hidden (which bit us repeatedly inside `.layer` / `.pn`
  // containers). Coords are computed from the trigger's getBoundingClientRect
  // on open and whenever the viewport scrolls/resizes while open. It flips
  // above the trigger when there isn't enough room below.
  let { options = [], value = $bindable(), onchange = null, minWidth = '150px' } = $props();
  let open = $state(false);
  let root;
  let menu;
  // Hide until place() runs once, so the initial render at viewport (0,0)
  // isn't visible for one frame while we measure scrollHeight.
  let menuStyle = $state('visibility:hidden;');
  const selected = $derived(options.find((o) => o.v === value) ?? options[0]);

  function pick(o) { value = o.v; open = false; onchange?.(); }
  function onDoc(e) {
    if (!root) return;
    if (root.contains(e.target)) return;
    if (menu && menu.contains(e.target)) return;
    open = false;
  }

  // Position logic. Dropdown's max height caps at 320px; the placement
  // picks whichever side (below or above the trigger) better fits the
  // menu's natural height, then clamps max-height to that side's room.
  const MARGIN = 4;
  const HARD_MAX = 320;

  function place() {
    if (!root || !menu) return;
    const r = root.getBoundingClientRect();
    const vh = window.innerHeight;
    const spaceBelow = vh - r.bottom - MARGIN;
    const spaceAbove = r.top - MARGIN;
    // Measure what the menu WANTS to be (its uncapped natural height).
    // scrollHeight on the already-rendered menu reflects the full content.
    const natural = Math.min(HARD_MAX, menu.scrollHeight);
    // Flip up when the menu doesn't fit below AND above has strictly more
    // room. Below stays the default when both sides fit or when below is
    // at least as roomy.
    const flipUp = natural > spaceBelow && spaceAbove > spaceBelow;
    const maxH = Math.max(80, Math.min(HARD_MAX, flipUp ? spaceAbove : spaceBelow));
    const h = Math.min(natural, maxH);
    const top = flipUp ? Math.max(MARGIN, r.top - MARGIN - h) : r.bottom + MARGIN;
    menuStyle = `visibility:visible; left:${r.left}px; top:${top}px; min-width:${r.width}px; max-height:${maxH}px;`;
  }

  $effect(() => {
    if (!open) {
      // Reset so the next open starts with the hidden pre-measure style
      // instead of flashing at the old coords.
      menuStyle = 'visibility:hidden;';
      return;
    }
    // Place now and after the menu has a first layout pass (offsetHeight stable).
    requestAnimationFrame(place);
    document.addEventListener('click', onDoc);
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      document.removeEventListener('click', onDoc);
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  });
</script>

<div class="dd" bind:this={root} style="min-width:{minWidth}">
  <button type="button" class="ddbtn" class:open onclick={() => (open = !open)}>
    <span class="ddlabel">{selected?.l ?? ''}</span>
    <span class="ddcaret">▾</span>
  </button>
  {#if open}
    <div class="ddmenu" bind:this={menu} style={menuStyle}>
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

  /* Fixed positioning so the menu escapes every ancestor's overflow:hidden.
     Coords + max-height come from the place() script above. */
  .ddmenu {
    position: fixed;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 5px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    overflow: auto;
  }
  /* flex: 0 0 auto so items keep their natural height when the column
     overflows and the menu scrolls instead of compressing every row. */
  .dditem { flex: 0 0 auto; text-align: left; background: transparent; border: none; border-radius: var(--radius); color: var(--text-body); font-family: var(--font-sans); font-size: var(--fs-13); line-height: 1.4; padding: 8px 11px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .dditem:hover { background: var(--panel-2); }
  .dditem.on { background: var(--accent-fill); color: var(--text); }
</style>
