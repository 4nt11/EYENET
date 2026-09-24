<script>
  // Segmented toggle (All / Users / Bots …). options: [{ v, l }]; value is one of
  // the option `v`s (any type, compared with ===).
  let { options = [], value = $bindable(), onchange = null } = $props();
  function pick(v) { value = v; onchange?.(); }
</script>

<div class="seg">
  {#each options as o}
    <button type="button" class:on={o.v === value} onclick={() => pick(o.v)}>{o.l}</button>
  {/each}
</div>

<style>
  .seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--radius); overflow: hidden; height: 28px; flex: 0 0 auto; }
  .seg button { appearance: none; background: transparent; border: none; border-right: 1px solid var(--border-strong); color: var(--text-secondary); font-family: var(--font-sans); font-size: var(--fs-12); padding: 0 10px; cursor: pointer; }
  .seg button:last-child { border-right: none; }
  .seg button.on { background: var(--accent-fill); color: var(--text); }
  .seg button:hover:not(.on) { background: var(--panel); }
</style>
