<script>
  // Reusable floating search-and-pick palette. Extracted from the graph
  // page's quickAdd pattern. Zero behaviour change for that caller; the
  // rule editor (+ future callers) can reuse this for family pickers,
  // actor / persona / artifact search, etc.
  //
  // Props:
  //   open         : $bindable boolean; parent opens / closes it.
  //   position     : {x, y} viewport-space anchor (fixed-positioned).
  //                  Panel centers on this point.
  //   anchor       : HTMLElement. If passed, the panel drops below the
  //                  anchor's bounding rect with the same width (replaces
  //                  position + width). Use this for form-field triggers
  //                  so the picker looks like a continuation of the input.
  //   width        : CSS width for the panel (default 280px). Ignored
  //                  when `anchor` is set (anchor width wins).
  //   search       : async (query) => results[]. Called debounced on
  //                  every keystroke. For static lists, pass a sync fn
  //                  returning a filtered array.
  //   resultKey    : (r) => string | number. Unique key for {#each}.
  //   resultLabel  : (r) => string. Row label.
  //   resultDot    : optional (r) => string. CSS color for the leading
  //                  bullet. Defaults to --accent-text.
  //   placeholder  : input placeholder text.
  //   onPick       : (r) => void. Fired when an item is clicked or
  //                  Enter is pressed on it.
  //   onCreate     : optional (query) => void. When provided, a
  //                  "+ Create ..." row appears below the results and
  //                  fires with the current query string.
  //   createLabel  : optional (query) => string. Create-row text.
  //   initialQuery : optional string to pre-fill the input.
  //   debounceMs   : debounce interval. Default 180ms.
  let {
    open = $bindable(false),
    position = null,
    anchor = null,
    width = '280px',
    search,
    resultKey = (r) => r.id ?? r,
    resultLabel = (r) => r.label ?? r.title ?? String(r),
    resultDot = null,
    placeholder = 'Search...',
    onPick,
    onCreate = null,
    createLabel = (q) => (q ? `+ Create "${q}"` : '+ Create'),
    initialQuery = '',
    debounceMs = 180,
  } = $props();

  // Derive the effective style from anchor > position > center.
  // Starts hidden so the brief frame between open and the first
  // measurement doesn't flash the panel at viewport (0, 0).
  let anchorStyle = $state('visibility:hidden;');
  function placeFromAnchor() {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    anchorStyle = `visibility:visible; left:${r.left}px; top:${r.bottom + 4}px; width:${r.width}px;`;
  }

  let input;
  let q = $state(initialQuery);
  let results = $state([]);
  let sel = $state(0);
  let timer = null;

  function doFocus(node) { node.focus(); }

  async function runSearch() {
    try {
      const r = await search(q);
      results = Array.isArray(r) ? r : [];
      sel = 0;
    } catch {
      results = [];
      sel = 0;
    }
  }

  function onInput() {
    clearTimeout(timer);
    timer = setTimeout(runSearch, debounceMs);
  }

  function onKey(e) {
    if (!open) return;
    const createRowAt = onCreate ? results.length : -1;
    const maxIdx = onCreate ? results.length : results.length - 1;
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, Math.max(maxIdx, 0)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); }
    else if (e.key === 'Escape') { e.preventDefault(); open = false; }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (sel === createRowAt) { if (q.trim() && onCreate) onCreate(q.trim()); }
      else if (results[sel]) { onPick(results[sel]); }
    }
  }

  function onDoc(e) {
    const root = document.querySelector('.qp-root[data-qp-open="true"]');
    if (!root) return;
    if (!root.contains(e.target)) open = false;
  }

  $effect(() => {
    if (!open) {
      anchorStyle = 'visibility:hidden;';
      return;
    }
    q = initialQuery;
    sel = 0;
    runSearch();
    if (anchor) {
      placeFromAnchor();
      window.addEventListener('scroll', placeFromAnchor, true);
      window.addEventListener('resize', placeFromAnchor);
    }
    document.addEventListener('mousedown', onDoc);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      if (anchor) {
        window.removeEventListener('scroll', placeFromAnchor, true);
        window.removeEventListener('resize', placeFromAnchor);
      }
    };
  });
</script>

{#if open}
  <div
    class="qp-root"
    data-qp-open="true"
    style={anchor
      ? anchorStyle
      : position
        ? `left:${position.x}px; top:${position.y}px; transform:translate(-50%, -50%); width:${width};`
        : `left:50%; top:30%; transform:translateX(-50%); width:${width};`}
    role="dialog"
    aria-modal="false"
  >
    <input
      bind:this={input}
      class="qp-input"
      bind:value={q}
      use:doFocus
      oninput={onInput}
      onkeydown={onKey}
      spellcheck="false"
      autocomplete="off"
      {placeholder}
    />
    <div class="qp-list" role="listbox">
      {#each results as r, i (resultKey(r))}
        <button
          type="button"
          class="qp-row"
          class:sel={sel === i}
          role="option"
          aria-selected={sel === i}
          onmouseenter={() => (sel = i)}
          onclick={() => onPick(r)}
        >
          <span class="dot" style="background:{resultDot ? resultDot(r) : 'var(--accent-text)'}"></span>
          <span class="qp-t">{resultLabel(r)}</span>
        </button>
      {/each}
      {#if onCreate}
        <button
          type="button"
          class="qp-row qp-new"
          class:sel={sel === results.length}
          onmouseenter={() => (sel = results.length)}
          onclick={() => q.trim() && onCreate(q.trim())}
        >
          {createLabel(q.trim())}
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  /* Same visual as the graph's .qa / .qa-input / .qa-list / .qa-row,
     generalised with a qp- prefix. Fixed positioning so the panel escapes
     every overflow:hidden ancestor and sits in the viewport. */
  .qp-root {
    position: fixed;
    z-index: 1100;
    box-sizing: border-box;
    background: var(--panel-2, var(--surface));
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }
  .qp-input {
    width: 100%;
    height: 30px;
    padding: 0 10px;
    background: var(--surface);
    border: 0;
    border-bottom: 1px solid var(--border);
    color: var(--text-body);
    font-family: var(--font-mono);
    font-size: var(--fs-12);
  }
  .qp-input:focus { outline: none; }
  .qp-list {
    max-height: 260px;
    overflow-y: auto;
  }
  .qp-row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 7px 10px;
    background: none;
    border: 0;
    cursor: pointer;
    text-align: left;
  }
  .qp-row.sel { background: var(--surface); }
  .qp-row .dot {
    flex: 0 0 auto;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .qp-t {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-sans);
    font-size: var(--fs-12);
    color: var(--text-body);
  }
  .qp-new {
    font-family: var(--font-mono);
    font-size: var(--fs-11);
    color: var(--accent-text);
    border-top: 1px solid var(--border);
  }
  .qp-new .qp-t { color: var(--accent-text); }
</style>
