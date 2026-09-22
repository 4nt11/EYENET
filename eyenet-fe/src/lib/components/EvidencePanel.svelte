<script>
  import Panel from './Panel.svelte';
  // Key/value evidence. items: [{ label, value, mono?, tone? }]  (mono defaults true)
  let { title, items = [], labelWidth = 128 } = $props();
  const toneColor = (t) =>
    t === 'critical' ? 'var(--red-text)' : t === 'accent' ? 'var(--accent-text)' : 'var(--text-body)';
</script>

{#snippet inner()}
  <dl>
    {#each items as it, i}
      <div class="row" class:last={i === items.length - 1} style="--_lw:{labelWidth}px;">
        <dt>{it.label}</dt>
        <dd class:sans={it.mono === false} style="color:{toneColor(it.tone)};">{it.value}</dd>
      </div>
    {/each}
  </dl>
{/snippet}

{#if title}
  <Panel {title}>{@render inner()}</Panel>
{:else}
  <div class="bare">{@render inner()}</div>
{/if}

<style>
  .bare { border: 1px solid var(--border); border-radius: var(--radius); background: var(--panel); overflow: hidden; }
  dl { margin: 0; }
  .row {
    display: grid;
    grid-template-columns: var(--_lw) 1fr;
    gap: 12px;
    padding: 7px 12px;
    border-bottom: 1px solid var(--border);
    align-items: baseline;
  }
  .row.last { border-bottom: none; }
  dt {
    font-family: var(--font-sans);
    font-size: var(--fs-12);
    color: var(--text-faint);
    letter-spacing: .01em;
  }
  dd {
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--fs-12);
    letter-spacing: var(--tracking-data);
    word-break: break-all;
  }
  dd.sans { font-family: var(--font-sans); font-size: var(--fs-13); letter-spacing: normal; }
</style>
